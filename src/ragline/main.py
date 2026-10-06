"""Application entry point — assembles the FastAPI app.

Wires logging, the lifespan (DB init, Qdrant collection, BM25 rebuild,
reranker warmup), the auth posture checks, every API router, and the built
frontend.

Run with:  uvicorn ragline.main:app --host 127.0.0.1 --port 8000
(loopback on purpose — see SECURITY.md before binding a routable address).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from ragline import __version__
from ragline.api.routes import admin, batches, chat, documents, health, layout, query
from ragline.config import settings
from ragline.logging_utils import configure_redaction


def _configure_logging() -> None:
    """Set up structlog + stdlib logging at the configured level."""
    # Translate the config string ("info") into a stdlib level number.
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    # Basic stdlib config so uvicorn/third-party logs respect the level too.
    logging.basicConfig(level=level)
    # structlog: timestamped, level-tagged, key-value console output.
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
    configure_redaction()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging, DB tables, BM25 rebuild. Shutdown: just a log line."""
    # ---- startup ----
    _configure_logging()
    log = structlog.get_logger()
    log.info("ragline starting", version=__version__)

    # Create all SQLite tables (idempotent).
    from ragline.storage.metadata_db import init_db

    await init_db()

    # Session hygiene: drop sessions past their absolute expiry. Cheap (one
    # DELETE), and running it at startup means the table can never grow
    # unboundedly across restarts even if no external scheduler exists.
    if settings.auth_enabled:
        from ragline.storage.auth_models import purge_expired_sessions

        purged = await purge_expired_sessions()
        if purged:
            log.info("purged expired sessions", count=purged)

    # One-time migration for pre-auth deployments: chat sessions used to live
    # loose in memory_dir; with auth on they are namespaced per user oid.
    # Loose files are parked in _legacy/ (recoverable, invisible to users)
    # rather than deleted or claimed by whoever signs in first.
    if settings.auth_enabled:
        from pathlib import Path

        memory_root = Path(settings.memory_dir)
        loose = list(memory_root.glob("*.json"))
        if loose:
            legacy = memory_root / "_legacy"
            legacy.mkdir(parents=True, exist_ok=True)
            for f in loose:
                f.rename(legacy / f.name)
            log.info("moved pre-auth chat sessions to _legacy", count=len(loose))

    # Rebuild the in-memory BM25 index from existing vectors so sparse
    # search works immediately after a restart. Failure (e.g. Qdrant down)
    # degrades to dense-only search rather than blocking startup.
    try:
        from ragline.api.dependencies import get_retrieval_pipeline

        # Constructing the pipeline loads the CrossEncoder reranker (~2GB,
        # synchronous CPU/IO). Build it in a worker thread so the event loop
        # isn't blocked for the whole load during startup.
        pipeline = await asyncio.to_thread(get_retrieval_pipeline)
        await pipeline.rebuild_bm25_index()
    except Exception as exc:  # noqa: BLE001 — startup must survive this
        log.warning("BM25 rebuild failed at startup; sparse search empty until next ingest",
                    error=str(exc))

    # Requeue ingestion batches a previous process left mid-flight. Batch
    # processing is an in-process asyncio task, so a restart strands its
    # documents in status='processing' — and the worker only ever picks up
    # 'pending', so without this reset they would never run again.
    try:
        from ragline.api.dependencies import (
            get_embedder,
            get_file_store,
            get_llm,
            get_retrieval_pipeline,
            get_vector_store,
        )
        from ragline.api.routes.health import probe_services
        from ragline.ingestion.worker import BatchWorker, spawn_background
        from ragline.storage.metadata_db import (
            find_unfinished_batches,
            get_batch_documents,
            update_document,
        )

        unfinished = await find_unfinished_batches()
        if unfinished:
            vector_store = get_vector_store()
            # Reset stranded documents first — this part is always safe and
            # idempotent, whether or not we respawn below.
            requeued = 0
            for batch in unfinished:
                for doc in await get_batch_documents(batch.id):
                    if doc.status == "processing":
                        # Defensive: drop any half-written vectors so the
                        # re-run cannot leave duplicate points behind.
                        await vector_store.delete_by_document_id(doc.id)
                        await update_document(doc.id, status="pending", stage="")
                        requeued += 1

            # Only respawn when the embedder answers (and the LLM, when graph
            # extraction needs it): resuming against a dead pod would burn
            # every document's retry budget into 'error'. Skipping is safe —
            # documents stay 'pending' and the next restart tries again.
            services = await probe_services()
            resumable = services["embedder"] and (
                services["llm"] or not settings.enable_knowledge_graph
            )
            if resumable:
                for batch in unfinished:
                    worker = BatchWorker(
                        get_file_store(), get_embedder(), vector_store,
                        get_retrieval_pipeline(), llm=get_llm(),
                    )
                    spawn_background(worker.process_batch(batch.id))
                log.info("requeued unfinished batches",
                         batches=len(unfinished), reset_docs=requeued)
            else:
                log.warning("unfinished batches found but backend is down; "
                            "left paused — restart once the pod is up",
                            batches=len(unfinished), reset_docs=requeued)
    except Exception as exc:  # noqa: BLE001 — startup must survive this too
        log.warning("batch requeue failed at startup", error=str(exc))

    # Hand control to the running application.
    yield
    # ---- shutdown ----
    structlog.get_logger().info("ragline stopped")


# The ASGI application object uvicorn serves.
app = FastAPI(title="ragline", version=__version__, lifespan=lifespan)

# All API routes live under /api; the bare paths stay free for the frontend.
app.include_router(health.router, prefix="/api")
# layout before documents: its fixed /documents/layout/... paths must never be
# read as a {document_id} by the documents router's parameterised routes.
app.include_router(layout.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(batches.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# --- Auth (Entra SSO, backend-for-frontend) --------------------------------
# The auth router is always mounted (auth/me tells the UI whether auth is on);
# the enforcing middleware only when enabled. AUTH_ENABLED=false is the dev
# escape hatch — everything runs as one local "dev" identity.
from ragline.auth import oidc as auth_oidc  # noqa: E402
from ragline.auth.middleware import AuthMiddleware  # noqa: E402

app.include_router(auth_oidc.router, prefix="/api")

def _enforce_auth_posture() -> None:
    """Refuse the dev escape hatch unless this is an EXPLICITLY marked dev box.

    Keys off the pydantic-PARSED boolean, so every falsey spelling
    (AUTH_ENABLED=false/0/no/off, quoted or not) and a systemd Environment=
    override are all caught here — a text grep over .env (the systemd
    ExecStartPre) cannot see those and is only defense-in-depth. Turning auth
    off requires RAGLINE_ALLOW_INSECURE_DEV=1; without it, serving the whole
    corpus unauthenticated fails loudly at startup.
    """
    import os

    # The flag counts from either source: exported env var (how tests set it)
    # or a .env entry (settings.ragline_allow_insecure_dev — how a dev box sets
    # it). Prod is independently protected: the systemd ExecStartPre grep
    # refuses any falsey AUTH_ENABLED in .env regardless of this flag.
    allow_insecure = (
        os.environ.get("RAGLINE_ALLOW_INSECURE_DEV") == "1" or settings.ragline_allow_insecure_dev
    )
    if not settings.auth_enabled and not allow_insecure:
        raise RuntimeError(
            "AUTH_ENABLED is off but RAGLINE_ALLOW_INSECURE_DEV is not set to 1. "
            "Refusing to serve unauthenticated — this exposes every ingested "
            "document to the network. For local development set "
            "RAGLINE_ALLOW_INSECURE_DEV=1; otherwise enable auth."
        )


_enforce_auth_posture()

if settings.auth_enabled:
    _missing = [
        name
        for name, value in [
            ("ENTRA_TENANT_ID", settings.entra_tenant_id),
            ("ENTRA_CLIENT_ID", settings.entra_client_id),
            ("ENTRA_CLIENT_SECRET", settings.entra_client_secret),
            ("SESSION_SECRET", settings.session_secret),
            ("APP_BASE_URL", settings.app_base_url),
        ]
        if not value
    ]
    if _missing:
        # Fail fast and loud: a half-configured auth layer must never serve.
        # Local development without an Entra tenant sets AUTH_ENABLED=false.
        raise RuntimeError(
            "AUTH_ENABLED=true but required settings are missing: "
            + ", ".join(_missing)
            + ". Set them in .env, or set AUTH_ENABLED=false for local dev."
        )
    # add_middleware order: last added runs first, so Session (the login
    # dance's state/nonce cookie) wraps Auth, which wraps the app.
    app.add_middleware(AuthMiddleware)
    from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=True,
    )

# Serve the built frontend (frontend/dist) at / when it exists — same
# pattern as raggles: html=True serves index.html for the root path, and
# the try/except keeps the API usable before the frontend is built.
try:
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
except Exception:
    pass  # Frontend not built yet — API-only mode.
