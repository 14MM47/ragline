"""smoke_llm.py — prove the single-endpoint abstraction works.

Sends ONE chat completion and ONE embedding request through ragline's
provider layer against whatever endpoint .env configures, and prints the
token usage captured by the TraceCollector. Run this after every endpoint
migration (OpenAI -> RunPod vLLM -> on-prem) to confirm nothing else needs
to change.

Usage:  python scripts/smoke_llm.py        (from the repo root)
"""

import asyncio
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, "src")

from ragline.config import settings  # noqa: E402
from ragline.embeddings.factory import get_embedder  # noqa: E402
from ragline.llm.factory import get_llm  # noqa: E402
from ragline.tracing.collector import TraceCollector  # noqa: E402


async def main() -> int:
    """Run the two smoke calls; return a process exit code."""
    # The script takes no arguments; -h/--help prints the usage text and
    # exits without calling any endpoint.
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(__doc__)
        return 0
    # Show exactly which endpoint/models we're about to hit.
    print(f"LLM endpoint       : {settings.llm_base_url}  (model: {settings.llm_model})")
    print(f"Embedding endpoint : {settings.effective_embedding_base_url}  (model: {settings.embedding_model})")

    # A collector so the provider's automatic token accounting is visible.
    trace = TraceCollector(query="smoke test")

    # --- 1. Chat completion through the provider layer ---
    llm = get_llm()
    answer = await llm.complete(
        [{"role": "user", "content": "Reply with exactly the word: pong"}]
    )
    print(f"completion reply   : {answer.strip()!r}")

    # --- 2. Embedding through the embedder layer ---
    embedder = get_embedder()
    vector = await embedder.embed_query("industrial automation datasheet")
    print(f"embedding dims     : {len(vector)}")

    # --- 3. Token accounting captured automatically by the ContextVar trace ---
    record = trace.finalize()
    print(f"tokens (prompt/completion): {record.prompt_tokens}/{record.completion_tokens}")

    # Success requires a non-empty answer, a plausible vector, and token counts.
    ok = bool(answer.strip()) and len(vector) > 0 and record.prompt_tokens > 0
    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    # asyncio.run drives the async main; exit code feeds CI/scripts.
    raise SystemExit(asyncio.run(main()))
