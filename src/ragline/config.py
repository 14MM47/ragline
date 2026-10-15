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
    # Extra JSON merged into EVERY chat-completion request body as the SDK's
    # `extra_body` (server-specific parameters the OpenAI schema has no field
    # for). The evaluation campaign uses it to switch a hybrid model's thinking
    # mode per run, e.g. '{"chat_template_kwargs": {"enable_thinking": true}}'
    # against vLLM. Empty = send nothing extra (production default). Must be a
    # JSON object; validated at startup so a typo fails loudly, not per call.
    llm_extra_body: str = ""
    # Extra JSON merged over LLM_EXTRA_BODY for ANSWER generation only (the RAG
    # answer and the library answer) — not for the query pre-pass, confidence,
    # memory or graph extraction. Lets thinking be switched on where it can
    # improve the answer without making every side call reason (slow, and a
    # truncation risk for their small output ceilings). Nested objects such as
    # chat_template_kwargs merge key by key. Empty = answers send LLM_EXTRA_BODY
    # unchanged (production default). Same JSON-object rules as LLM_EXTRA_BODY.
    answer_extra_body: str = ""
    # Sampling temperature for ANSWER generation only (RAG and library answers).
    # Empty = the caller's own temperature (0.0, greedy — production default).
    # Exists because thinking models are tuned for sampled decoding: Qwen's
    # thinking-mode guidance is temperature 0.6 (top_p/top_k/min_p go through
    # ANSWER_EXTRA_BODY) and warns that greedy decoding degrades answers and
    # causes endless repetition. `temperature` itself is a reserved key in the
    # extra bodies, hence a setting of its own.
    answer_temperature: float | None = None

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

    @field_validator("llm_extra_body", "answer_extra_body")
    @classmethod
    def _extra_body_is_json_object(cls, v: str, info) -> str:
        """Accept empty or a JSON object; reject anything else at startup."""
        # Empty (or whitespace) means "no extra body" — normalise to "".
        if not v or not v.strip():
            return ""
        import json

        # Must parse, and must be an object: the SDK merges extra_body as a
        # mapping, so a list or scalar would only fail later, inside a request.
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{info.field_name.upper()} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{info.field_name.upper()} must be a JSON object, e.g. {{\"key\": value}}")
        # The SDK merges extra_body OVER the named parameters, so these keys
        # would silently redirect or rewrite every request if .env were tampered.
        reserved = {"model", "messages", "temperature", "max_tokens", "stream", "stream_options",
                    "n", "stop", "tools", "tool_choice", "response_format"}
        clash = sorted(set(parsed) & reserved)
        if clash:
            raise ValueError(f"{info.field_name.upper()} may not set request parameters: {clash}")
        return v

    @field_validator("embedding_dimensions", "answer_temperature", mode="before")
    @classmethod
    def _blank_int_is_none(cls, v):  # also ANSWER_TEMPERATURE (see the decorator)
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
    # Spare reranked candidates kept so dropped duplicates / fragments can be
    # backfilled without a second rerank (ragline-fixes-plan item 5).
    rerank_spare: int = 4
    # Chunks shorter than this (characters) are fragments — page footers, a
    # lone document code — and are dropped from the final context.
    min_context_chars: int = 100
    # Comparison / multi-entity questions: one retrieval per named product, with
    # this many reserved slots each in the final context (0 = per-entity off).
    entity_slots: int = 2
    # At most this many per-product sub-queries are run for one question.
    max_entity_queries: int = 4
    # In a multi-product context, the main query's fill takes at most this many
    # chunks from any one document (the reserved product slots are not capped).
    entity_doc_cap: int = 4
    # Add the next chunk of a hit that ends inside (or is followed by) a table or
    # numbered list — recovers rows and steps split across chunks/pages.
    neighbour_expansion: bool = True
    neighbour_max_added: int = 4                     # cap on neighbour chunks added
    enable_context_reordering: bool = True           # lost-in-the-middle mitigation
    enable_hyde: bool = False                        # reserved: accepted but unused (no HyDE code path)

    # ------------------------------------------------------------------
    # Chunking / parsing.
    # ------------------------------------------------------------------
    chunk_max_tokens: int = 512                      # token budget per chunk
    chunk_overlap_fraction: float = 0.15             # overlap carried into next chunk
    chunk_min_tokens: int = 48                       # smaller chunks fold into a same-page neighbour
    enable_layout_analysis: bool = True              # strip repeated headers/footers
    enable_ocr_fallback: bool = True                 # OCR pages with <50 chars of text
    parse_cache_dir: str = ""                         # parsed-document cache (scripts/preparse.py); empty = off

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
    # Output ceilings for the side calls of a chat turn. Their normal outputs are
    # ~100-300 tokens of JSON; without a ceiling a degenerate generation (JSON
    # mode can loop on whitespace or repeat) runs to the model's full context —
    # ~14 min at 77 tok/s on the eval pod, which stalled a run on 2026-10-14.
    prepass_max_tokens: int = 1024                   # structured pre-pass (rewrite + route)
    post_pass_max_tokens: int = 1024                 # memory post-pass (summary, key facts)
    confidence_max_tokens: int = 1024                # confidence pass (score + report)
    # Any model call slower than this is logged with its purpose, duration and
    # tokens, so a stall names the call that caused it. 0 disables the warning.
    llm_slow_call_s: float = 120.0
    # EVALUATION ONLY: keep the full text of every model call on the query
    # trace — messages sent, response, and the separated reasoning text — for
    # the harness to write to a transcript sidecar. Off in production: with it
    # off, reasoning text is never stored (only its length is counted).
    llm_capture_transcripts: bool = False

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

    @property
    def llm_extra_body_dict(self) -> dict:
        """LLM_EXTRA_BODY parsed to a dict; {} when unset.

        Parsed on each access (cheap, a few bytes) so a test or script that
        assigns `settings.llm_extra_body` after construction is honoured.
        """
        if not self.llm_extra_body:
            return {}
        import json

        return json.loads(self.llm_extra_body)

    @field_validator("answer_temperature")
    @classmethod
    def _answer_temperature_in_range(cls, v):
        """None (unset) or a sampling temperature the OpenAI API accepts (0-2)."""
        if v is not None and not 0.0 <= v <= 2.0:
            raise ValueError("ANSWER_TEMPERATURE must be between 0 and 2")
        return v

    @property
    def answer_extra_body_dict(self) -> dict:
        """ANSWER_EXTRA_BODY parsed to a dict; {} when unset (parsed per access, as above)."""
        if not self.answer_extra_body:
            return {}
        import json

        return json.loads(self.answer_extra_body)

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
