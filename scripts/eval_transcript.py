"""eval_transcript.py — print one question's full exchange from a transcript sidecar.

    python scripts/eval_transcript.py eval/results/eval-2026-10/r3/on/r1.transcripts.jsonl.gz A09
    python scripts/eval_transcript.py <sidecar> A09 --purpose answer --no-messages

Shows every model call of the question in order: purpose, tokens, time, how it
ended, then the messages sent, the reasoning and the response. For error
analysis next to the judge's verdict in rN.judge.json.
"""

import argparse
import gzip
import json
from pathlib import Path


def load_question(sidecar: Path, qid: str) -> dict | None:
    """The sidecar line for question `qid`, or None."""
    with gzip.open(sidecar, "rt", encoding="utf-8") as fh:
        for line in fh:
            entry = json.loads(line)
            if entry.get("id") == qid:
                return entry
    return None


def render(entry: dict, purpose: str | None = None, messages: bool = True) -> str:
    """The exchange as readable text."""
    out = [f"# {entry['id']}: {entry.get('question', '')}"]
    for n, call in enumerate(entry.get("calls", []), 1):
        if purpose and call.get("purpose") != purpose:
            continue
        out.append(f"\n## call {n}: {call.get('purpose') or 'unlabelled'} — "
                   f"prompt {call.get('prompt_tokens')} / completion {call.get('completion_tokens')} tokens, "
                   f"{call.get('ms')} ms, {call.get('tok_s')} tok/s, finish {call.get('finish_reason')}, "
                   f"temperature {call.get('temperature')}, max {call.get('max_tokens')}")
        if messages:
            for m in call.get("messages", []):
                out.append(f"\n### {m.get('role')}\n{m.get('content')}")
        if call.get("reasoning"):
            out.append(f"\n### reasoning ({len(call['reasoning'])} chars)\n{call['reasoning']}")
        out.append(f"\n### response\n{call.get('response', '')}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """Parse args, find the question, print its exchange."""
    parser = argparse.ArgumentParser(description="Print one question's model calls from a transcript sidecar")
    parser.add_argument("sidecar", help="rN.transcripts.jsonl.gz")
    parser.add_argument("question_id", help="Golden question id, e.g. A09")
    parser.add_argument("--purpose", default=None, help="Only calls with this purpose (answer, prepass, …)")
    parser.add_argument("--no-messages", action="store_true", help="Omit the prompts sent")
    args = parser.parse_args(argv)
    entry = load_question(Path(args.sidecar), args.question_id)
    if entry is None:
        print(f"{args.question_id} not found in {args.sidecar}")
        return 1
    print(render(entry, args.purpose, not args.no_messages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
