"""Health endpoint — liveness plus a soft dependency check.

GET /api/health reports the app version, whether Qdrant is reachable, and
whether each inference service (LLM, embedder, reranker) answers. It never
raises: a down dependency is reported in the body, not as a 5xx, so the
endpoint stays usable for load-balancer liveness probes — and the frontend
header uses the booleans to show pod up/down status and to guard ingestion
against a dead backend.
"""

import asyncio
import time

import httpx
import structlog
from fastapi import APIRouter, Depends, Request

from ragline import __version__
from ragline.api.dependencies import get_vector_store
from ragline.config import settings
from ragline.vectorstore.base import BaseVectorStore

log = structlog.get_logger()

router = APIRouter(tags=["health"])

# Per-probe HTTP timeout: fail fast, this runs inside a UI poll.
_PROBE_TIMEOUT_S = 2.0
# Snapshot cache: the UI may poll aggressively, but probing three remote
# services per request would hammer the pod (and slow every poll to the
# slowest probe). One shared snapshot, refreshed at most every 30 s.
_CACHE_TTL_S = 30.0
_cache: dict = {"expires": 0.0, "data": None}
# Single-flight guard so concurrent polls during a refresh don't stack probes.
_refresh_lock = asyncio.Lock()


def _service_root(base_url: str) -> str:
    """The server root of an OpenAI-style base URL (strip a trailing /v1)."""
    return base_url.rstrip("/").removesuffix("/v1")


async def _probe(client: httpx.AsyncClient, urls: list[str], api_key: str) -> bool:
    """True when any of `urls` answers 2xx (auth'd when a key is configured).

    Multiple candidate URLs cover the two server shapes we point at: TEI
    serves GET /health at its root; vLLM/OpenAI serve GET /v1/models. Only a
    2xx counts as up — RunPod's proxy answers 404 for a DEAD pod id, and a
    stale pod URL is exactly the failure this probe exists to surface.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    for url in urls:
        try:
            resp = await client.get(url, headers=headers)
            if 200 <= resp.status_code < 300:
                return True
        except Exception:  # noqa: BLE001 — connection errors just mean "down"
            continue
    return False


async def probe_services() -> dict[str, bool | None]:
    """Probe LLM, embedder and reranker reachability concurrently.

    Public because startup (main.py) reuses it to decide whether requeued
    batches can safely resume — resuming against a dead embedder would just
    error every document through its retry budget.
    """
    llm_root = _service_root(settings.llm_base_url)
    embed_root = _service_root(settings.effective_embedding_base_url)
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        probes = [
            # LLM: vLLM and OpenAI-compatible servers all serve /v1/models.
            _probe(client, [f"{llm_root}/v1/models"], settings.llm_api_key),
            # Embedder: TEI answers /health at its root; an OpenAI-style
            # fallback (embedding served by the LLM endpoint) answers /v1/models.
            _probe(
                client,
                [f"{embed_root}/health", f"{embed_root}/v1/models"],
                settings.effective_embedding_api_key,
            ),
        ]
        # Reranker: only probeable when it IS a remote service; the local
        # cross-encoder and "none" have no endpoint — reported as null (n/a).
        if settings.reranker_provider == "api" and settings.reranker_base_url:
            probes.append(_probe(
                client,
                [f"{_service_root(settings.reranker_base_url)}/health"],
                settings.reranker_api_key,
            ))
            llm_ok, embed_ok, rerank_ok = await asyncio.gather(*probes)
        else:
            llm_ok, embed_ok = await asyncio.gather(*probes)
            rerank_ok = None
    return {"llm": llm_ok, "embedder": embed_ok, "reranker": rerank_ok}


@router.get("/health")
async def health(
    request: Request, vector_store: BaseVectorStore = Depends(get_vector_store)
) -> dict:
    """Return liveness info and soft dependency status (cached ~30 s).

    The route is on the auth allowlist so external monitors work, but
    anonymous callers get ONLY {"status": ...} — version and per-service
    booleans are mild recon (what's deployed, what's down) and reserved for
    signed-in users (the middleware attaches the user even on allowlisted
    paths). With auth disabled everyone gets the full body, as before.
    """
    authenticated = (not settings.auth_enabled) or (
        getattr(request.state, "user", None) is not None
    )

    # Serve the cached snapshot while it is fresh — keeps the endpoint cheap
    # under the frontend's polling and under any external liveness probe.
    now = time.monotonic()
    if _cache["data"] is not None and now < _cache["expires"]:
        return _cache["data"] if authenticated else {"status": _cache["data"]["status"]}

    async with _refresh_lock:
        # Re-check inside the lock: another poll may have refreshed already.
        now = time.monotonic()
        if _cache["data"] is not None and now < _cache["expires"]:
            return _cache["data"] if authenticated else {"status": _cache["data"]["status"]}

        # Reuse the process-wide vector-store client (bounded, fast, never
        # raises) instead of a throwaway client per probe.
        qdrant_ok = await vector_store.ping()
        services = await probe_services()

        # "degraded" = the app is up but a dependency isn't. The reranker only
        # counts when it is a remote service (null = not applicable).
        critical_ok = qdrant_ok and services["llm"] and services["embedder"] \
            and services["reranker"] is not False
        # Deliberately NO backend details (base URLs, model names): this
        # endpoint is unauthenticated, and those fields hand any client the
        # reachable inference-pod addresses (security audit HIGH #2).
        # Booleans only; operators read URLs from .env / startup logs.
        _cache["data"] = {
            "status": "ok" if critical_ok else "degraded",
            "version": __version__,
            "qdrant": qdrant_ok,
            **services,
        }
        _cache["expires"] = time.monotonic() + _CACHE_TTL_S
        return _cache["data"] if authenticated else {"status": _cache["data"]["status"]}
