"""eval_prepass.py — eyeball the structured pre-pass rewrites against the live LLM.

Runs a fixed set of queries (some with a fake previous turn, to exercise
follow-up resolution) through exactly the prompt the chat agent uses —
STRUCTURED_PRE_PASS_SYSTEM + build_structured_pre_pass_user — and prints the
mode and rewrite for each. Run it before and after a prompt change and compare.

It checks the rewrites for the failures seen live (filler, meta phrases about
"the collection", acronym drift like hmis -> HMIS) and flags them, but the
real judgement is by eye: does each rewrite look like a good search query?

Usage (from the repo root):
        .venv/bin/python scripts/eval_prepass.py
        .venv/bin/python scripts/eval_prepass.py --baseline <git-ref>
The --baseline form runs the same cases with the system prompt as it was at
<git-ref> (e.g. the branch before a prompt change), for a before/after compare.
Uses the LLM endpoint from .env. Read-only: no memory is saved.
"""

import asyncio
import re
import subprocess
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, "src")

from ragline.chat.models import SessionMemory, TurnRecord  # noqa: E402
from ragline.chat.prepass_schema import PrePassResult  # noqa: E402
from ragline.chat.prompts import (  # noqa: E402
    STRUCTURED_PRE_PASS_SYSTEM,
    build_structured_pre_pass_user,
)
from ragline.config import settings  # noqa: E402
from ragline.llm.factory import get_llm  # noqa: E402

# (previous turn, new query); previous turn = (user question, assistant answer),
# or None for a first-turn query.
# Contexts deliberately avoid the prompt's own worked examples (PanelView 800 +
# "more about hmis" is example 1), so the run measures generalisation, not copying.
CASES = [
    (("tell me about the Siemens SIMATIC KTP700", "The KTP700 Basic is a 7-inch HMI touch panel…"),
     "more about hmis"),
    (None, "more about hmis"),
    (("which output module should I use for 24V DC loads?", "The 1756-OB16E is a 16-point 24V DC output module…"),
     "what's its max output current?"),
    (("what PLC do you recommend?", "The Modicon M580 (M580_datasheet.pdf) is a good fit…"),
     "anything else besides the M580?"),
    (None, "operating temperature range of the PanelView 5310"),
    (None, "compare plcs with ethernet/ip"),
    (None, "how many datasheets have been uploaded?"),
    (None, "which vendors are in the collection?"),
    (("what's the IP rating of the PanelView 800?", "The PanelView 800 front bezel is rated IP65…"),
     "and the 5510?"),
    (None, "please can you tell me more information about safety relays"),
]

# Failure patterns from the live incident (flagged, not failed — judge by eye).
_META = re.compile(r"\b(document collection|the collection|the library|in the context of|documents?)\b", re.I)
_FILLER = re.compile(r"\b(more information|tell me|can you|please)\b", re.I)


def _memory(prev) -> SessionMemory:
    """A session with zero or one prior turn."""
    memory = SessionMemory(session_id="eval", created_at="2026-09-23T00:00:00Z")
    if prev:
        q, a = prev
        # One synthetic past exchange so the builder emits 'Recent conversation'.
        memory.turns.append(TurnRecord(turn_number=1, user_query=q, rewritten_query=q, answer=a,
                                       spans=[], sources=[], model_used=settings.llm_model,
                                       timestamp="2026-09-23T00:00:00Z"))
        memory.summary = f"User asked: {q}"
    return memory


def _system_prompt(argv: list[str]) -> tuple[str, str]:
    """(system prompt, label): the working tree's, or --baseline <ref>'s from git."""
    if "--baseline" not in argv:
        return STRUCTURED_PRE_PASS_SYSTEM, "working tree"
    ref = argv[argv.index("--baseline") + 1]
    # Read prompts.py as it was at <ref> and execute it to get the constant
    # (argv list, no shell — the ref is passed to git verbatim).
    source = subprocess.run(["git", "show", f"{ref}:src/ragline/chat/prompts.py"],
                            check=True, capture_output=True, text=True).stdout
    namespace: dict = {}
    exec(compile(source, f"{ref}:prompts.py", "exec"), namespace)  # noqa: S102 — our own repo file
    return namespace["STRUCTURED_PRE_PASS_SYSTEM"], f"baseline {ref}"


async def main() -> int:
    """Run every case; print mode, rewrite and any flags; return an exit code."""
    # -h/--help prints the usage text and exits before any LLM call.
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(__doc__)
        return 0
    system_prompt, label = _system_prompt(sys.argv[1:])
    llm = get_llm()
    print(f"LLM: {settings.llm_base_url}  (model: {settings.llm_model})  prompt: {label}\n")
    flagged = 0
    for prev, query in CASES:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_structured_pre_pass_user(_memory(prev), query)},
        ]
        try:
            result: PrePassResult = await llm.complete_json(messages, PrePassResult)
        except Exception as e:  # noqa: BLE001 — report and continue with the next case
            print(f"[ERROR] {query!r}: {type(e).__name__}\n")
            flagged += 1
            continue
        rw = result.rewritten_query
        # Flag the incident's failure shapes (meta phrases only matter outside library mode).
        flags = []
        if result.mode != "library" and _META.search(rw):
            flags.append("META")
        if _FILLER.search(rw):
            flags.append("FILLER")
        if "hmis" in query.lower() and "HMIS" in rw:
            flags.append("ACRONYM")
        flagged += bool(flags)
        ctx = f"(after: {prev[0]!r}) " if prev else ""
        print(f"{'[' + ','.join(flags) + '] ' if flags else ''}{ctx}{query!r}")
        print(f"    mode={result.mode}  rewrite={rw!r}")
        extras = {k: v for k, v in (("excluded", result.excluded_sources),
                                    ("hints", result.target_document_hints),
                                    ("contrastive", result.has_contrastive_intent),
                                    ("collection_wide", result.is_collection_wide)) if v}
        if extras:
            print(f"    {extras}")
        print()
    print(f"{flagged} of {len(CASES)} cases flagged")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
