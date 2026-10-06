"""Application settings — the entire configuration surface of ragline.

Ported from raggles' config.py but cut from ~120 settings to ~30: every
playground feature flag (CRAG, Self-RAG, FLARE, ColPali, semantic cache,
A/B testing, guardrails, PII, ...) is gone. What remains is exactly what the
simplified pipeline uses. Each field maps 1:1 to an env var documented in
env.template at the repo root.
"""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Read values from a .env file in the working directory; env vars win.
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ------------------------------------------------------------------
    # LLM endpoint — ONE OpenAI-compatible endpoint for every LLM task:
    # chat answers, KG extraction, structured pre-pass, memory post-pass,
    # confidence scoring. Swapping cloud -> RunPod vLLM -> on-prem GPU is
    # purely an env-var change (see env.template for the migration recipe).
    # ------------------------------------------------------------------
    llm_base_url: str = "https://api.openai.com/v1"  # OpenAI-compatible server root
    llm_api_key: str = ""                            # bearer token for that server
    llm_model: str = "gpt-4o"                        # model name as the server knows it

    # ------------------------------------------------------------------
    # Embeddings — same API shape. Empty base_url/api_key fall back to the
    # LLM values (see the effective_* properties below), because on OpenAI
    # cloud a single endpoint serves both, while a self-hosted vLLM serves
    # one model per instance and therefore needs its own URL.
    # ------------------------------------------------------------------
    embedding_base_url: str = ""                     # empty = use llm_base_url
    embedding_api_key: str = ""                      # empty = use llm_api_key
    embedding_model: str = "text-embedding-3-large"  # embedding model name
    embedding_dimensions: int | None = None          # explicit dims for servers that need it
    # Retrieval task instruction prepended to QUERIES only (never documents),
    # in Qwen3-Embedding's "Instruct: ...\nQuery:..." format. Qwen documents a
    # ~1-5% retrieval drop without it. Empty = raw queries (right for OpenAI
    # and other non-instruction embedders). Changing it needs no re-index.
    embedding_query_instruction: str = ""

    @field_validator("embedding_dimensions", mode="before")
    @classmethod
    def _blank_int_is_none(cls, v):
        """Treat an empty env value (EMBEDDING_DIMENSIONS=) as None.

        env.template ships this key blank to mean "use the model's native
        dimension"; without this, the empty string fails int parsing and
        breaks Settings() construction for any .env copied from the template.
        """
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # ------------------------------------------------------------------
    # Reranker — deliberately NOT behind the OpenAI-compatible endpoint (the
    # OpenAI API has no rerank operation). "local" = CPU cross-encoder in this
    # process | "api" = a TEI /rerank or Cohere-style /v1/rerank endpoint (e.g.
    # on the GPU pod) | "none" = skip reranking.
    # ------------------------------------------------------------------
    reranker_provider: str = "local"                 # local = cross-encoder on CPU
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # ~2GB download on first start
    # "api" provider: a TEI (text-embeddings-inference) /rerank endpoint, e.g.
    # a GPU pod serving bge-reranker-v2-m3 or Qwen3-Reranker-4B. Only used when
    # reranker_provider="api". Key is optional (TEI is often keyless).
    reranker_base_url: str = ""                       # e.g. http://<pod>:8080
    reranker_api_key: str = ""                        # bearer token, if the server needs one
    # Wire format of the "api" endpoint: "tei" = TEI native POST /rerank
    # {query, texts} -> [{index, score}]; "cohere" = POST /v1/rerank
    # {query, documents} -> {results: [{index, relevance_score}]}, as served
    # by vLLM (e.g. Qwen3-Reranker behind a pooling runner) and Cohere/Jina.
    reranker_api_format: str = "tei"
    # Skip the cross-encoder when dense scores already show a clear winner:
    # top >= min_top_score AND (top - mean of the rest) >= score_gap.
    reranker_skip_score_gap: float = 0.25
    reranker_skip_min_top_score: float = 0.5

    # ------------------------------------------------------------------
    # Vector store (Qdrant).
    # ------------------------------------------------------------------
    qdrant_host: str = "localhost"                   # docker compose exposes it here
    qdrant_port: int = 6333                          # Qdrant HTTP API port
    qdrant_collection: str = "ragline"               # single collection for all chunks

    # ------------------------------------------------------------------
    # Storage — SQLite metadata DB, uploaded files, session memory JSON.
    # ------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/ragline.db"  # async SQLite URL
    upload_dir: str = "./data/uploads"               # managed copies of uploaded docs
    memory_dir: str = "./data/memory"                # one JSON file per chat session
    # Built SPA served at /. Relative default suits dev (uvicorn from the repo
    # root); production sets an absolute path so no process — app, crawler, or
    # CLI script — depends on its working directory.
    frontend_dist: str = "frontend/dist"             # built frontend assets

    # ------------------------------------------------------------------
    # Auth — Entra SSO via backend-for-frontend OIDC. Sign-in happens on
    # login.microsoftonline.com; ragline never sees a password, only a
    # validated ID token, and issues its own opaque HttpOnly session cookie.
    # auth_enabled=false is a DEV-ONLY escape hatch (default is fail-closed):
    # every route then acts as a single local "dev" user.
    # ------------------------------------------------------------------
    auth_enabled: bool = True                        # false ONLY for local dev/tests
    # Confirms auth_enabled=false is intentional (main.py refuses to start
    # otherwise). Declared here so the key is legal in .env — pydantic-settings
    # forbids unknown .env keys, which is deliberate typo protection.
    ragline_allow_insecure_dev: bool = False
    entra_tenant_id: str = ""                        # directory (tenant) id
    entra_client_id: str = ""                        # app registration client id
    entra_client_secret: str = ""                    # client secret (calendar its expiry)
    entra_admin_group_id: str = ""                   # group whose members are ragline admins ("" = nobody)
    session_secret: str = ""                         # signs session + login-dance cookies
    app_base_url: str = ""                           # e.g. https://ragline.corp.example (redirect URI base)
    session_idle_hours: int = 12                     # sliding-expiry window
    session_absolute_days: int = 7                   # hard cap regardless of activity
    # How often a live session is silently re-validated against Entra (refresh
    # grant). This bounds REVOCATION LAG: a disabled account or revoked
    # sign-in session dies within this window, not at session expiry.
    session_revalidate_minutes: int = 60
    # true = logout also ends the Entra browser session (front-channel
    # sign-out). Needed on shared/kiosk machines; on personal devices the
    # default keeps "sign out of ragline" from meaning "sign out of M365".
    logout_from_entra: bool = False
    # File-based secret variants (systemd LoadCredential= / docker secrets):
    # when set, the file's contents override the corresponding value above,
    # keeping the secret out of .env entirely.
    entra_client_secret_file: str = ""
    session_secret_file: str = ""
    smb_password_file: str = ""

    # ------------------------------------------------------------------
    # ACL crawler — reads NTFS DACLs over SMB with a read-only service
    # account and gates citation links per user. Fail closed throughout.
    # ------------------------------------------------------------------
    smb_username: str = ""                           # crawler service account (DOMAIN\user or UPN)
    smb_password: str = ""                           # its password (read + READ_CONTROL only)
    # ";"-separated host aliases folding short names onto canonical ones,
    # e.g. "fs1=fs1.corp.example;nas=nas01.corp.example"
    smb_host_aliases: str = ""
    acl_stale_days: int = 7                          # crawl older than this grants nothing
    groups_cache_ttl_hours: int = 24                 # user group cache lifetime

    # ------------------------------------------------------------------
    # Retrieval tuning.
    # ------------------------------------------------------------------
    retrieval_top_k: int = 20                        # hybrid candidates before rerank
    rerank_top_k: int = 8                            # chunks that reach the LLM prompt
    enable_context_reordering: bool = True           # lost-in-the-middle mitigation
    enable_hyde: bool = False                        # reserved: accepted but unused (no HyDE code path)

    # ------------------------------------------------------------------
    # Chunking / parsing.
    # ------------------------------------------------------------------
    chunk_max_tokens: int = 512                      # token budget per chunk
    chunk_overlap_fraction: float = 0.15             # overlap carried into next chunk
    enable_layout_analysis: bool = True              # strip repeated headers/footers
    enable_ocr_fallback: bool = True                 # OCR pages with <50 chars of text

    # ------------------------------------------------------------------
    # Knowledge graph.
    # ------------------------------------------------------------------
    enable_knowledge_graph: bool = True              # extract entities at ingest time
    kg_extraction_concurrency: int = 20              # parallel extraction LLM calls
    # Output ceiling per extraction call. Without it a degenerate generation can
    # run to the model's full context (65k), holding a concurrency slot for
    # minutes — across ~113k corpus chunks that is a real tail risk. Set high
    # enough that a legitimately entity-dense chunk never truncates: a truncated
    # response is invalid JSON, which the extractor discards as "no entities".
    kg_extraction_max_tokens: int = 2048             # output cap per extraction call

    # ------------------------------------------------------------------
    # Chat behaviour.
    # ------------------------------------------------------------------
    use_structured_prepass: bool = True              # JSON pre-pass (rewrite + routing)
    enable_confidence: bool = True                   # post-answer confidence LLM call
    memory_token_budget: int = 1500                  # max memory tokens injected per turn
    intent_classifier: str = "keyword"               # library-mode detection strategy
    # Output ceilings for the two answer calls. A backstop, not the main lever
    # (the prompts ask for short answers): on a ~30 tok/s local model an
    # unbounded answer is minutes of waiting. A truncated RAG answer can lose
    # its last citation, so keep the RAG ceiling well above a normal answer.
    answer_max_tokens: int = 1500                    # output cap for a RAG answer
    library_answer_max_tokens: int = 600             # output cap for a library-mode answer

    # ------------------------------------------------------------------
    # Ingestion.
    # ------------------------------------------------------------------
    batch_max_parallel: int = 3                      # concurrent docs per batch
    batch_max_files: int = 1000                      # hard cap per batch upload
    # Server-side folder ingest: ";"-separated list of directories the
    # /api/batches/ingest-path endpoint may read from. Empty (the default)
    # disables the endpoint entirely — it reads server-local files by path,
    # so it must be an explicit operator opt-in, never on by default.
    ingest_roots: str = ""                           # e.g. /srv/corpora;/mnt/shares/eng

    @property
    def ingest_roots_list(self) -> list[str]:
        """The allowlisted ingest roots as a clean list (empty = disabled)."""
        return [r.strip() for r in self.ingest_roots.split(";") if r.strip()]

    # ------------------------------------------------------------------
    # Logging.
    # ------------------------------------------------------------------
    log_level: str = "info"                          # structlog/uvicorn level

    # ------------------------------------------------------------------
    # Derived values — fall-back logic for the embedding endpoint.
    # ------------------------------------------------------------------
    @property
    def effective_embedding_base_url(self) -> str:
        """Embedding server URL: explicit value, else the LLM server URL."""
        return self.embedding_base_url or self.llm_base_url

    @property
    def effective_embedding_api_key(self) -> str:
        """Embedding API key: explicit value, else the LLM API key."""
        return self.embedding_api_key or self.llm_api_key

    @model_validator(mode="after")
    def _load_file_secrets(self):
        """*_FILE variants win over inline values — the LoadCredential= path.

        Failing loudly on an unreadable file is deliberate: a configured-but-
        missing credential must stop startup, not silently fall back to an
        empty (or stale inline) secret.
        """
        for file_field, target in (
            ("entra_client_secret_file", "entra_client_secret"),
            ("session_secret_file", "session_secret"),
            ("smb_password_file", "smb_password"),
        ):
            path = getattr(self, file_field)
            if path:
                from pathlib import Path

                setattr(self, target, Path(path).read_text().strip())
        return self


# Single module-level instance imported everywhere (same pattern as raggles).
settings = Settings()
