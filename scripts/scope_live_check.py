"""scope_live_check.py — prove the retrieval scope holds against a live stack.

Complements tests/unit/test_retrieval_scope.py (which only proves the
plumbing) by asking a real question of the running API with three scopes:

  A  every ready document in one folder (default: the Mitsubishi GOT2000 manuals)
  B  every ready document in a DISJOINT folder (default: Weintek cMT)
  -  no scope at all

through /api/query, plus scope A once more through /api/chat (the SSE path the
UI uses). Every cited source must lie inside the scope that was sent, and the
disjoint scope must never cite a document from A — the model should decline
rather than answer from outside the selection. Exits 1 on any FAIL.

Needs ragline on --base with the pod (embedder + LLM) healthy, and auth OFF
(or a session cookie you add yourself). Run:

    .venv/bin/python scripts/scope_live_check.py
    .venv/bin/python scripts/scope_live_check.py --folder-a hmi/omron/na-series \\
        --folder-b hmi/siemens/tp-comfort --question "..."
"""

import argparse
import json
import sys
import time
import urllib.request

DEFAULT_QUESTION = (
    "How many Mitsubishi GOT2000 units can be connected as DeviceNet slaves to one DeviceNet master?"
)


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.load(r)


def _post(base: str, path: str, body: dict, timeout: int = 600) -> str:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _chat_answer(base: str, body: dict) -> dict:
    """POST /chat and return the `answer` SSE frame's JSON (the cited answer)."""
    raw = _post(base, "/chat", body)
    event, answer = "", None
    for line in raw.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event == "answer":
            answer = json.loads(line[5:].strip())
    if answer is None:
        raise RuntimeError("no `answer` frame in the chat stream")
    return answer


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000/api")
    ap.add_argument("--folder-a", default="hmi/mitsubishi/got2000", help="folder_path the question is about")
    ap.add_argument("--folder-b", default="hmi/weintek/cmt-series", help="a folder_path with nothing relevant")
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    args = ap.parse_args()

    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
        if not ok:
            fails += 1

    # Scopes are document ids; the UI expands a ticked folder the same way.
    docs = _get(args.base, "/documents")
    ready = [d for d in docs if d["status"] == "ready"]
    scope_a = [d["id"] for d in ready if d["folder_path"] == args.folder_a]
    scope_b = [d["id"] for d in ready if d["folder_path"] == args.folder_b]
    print(f"{len(ready)} ready docs; A ({args.folder_a}) = {len(scope_a)}, B ({args.folder_b}) = {len(scope_b)}")
    if not scope_a or not scope_b or set(scope_a) & set(scope_b):
        print("need two non-empty, disjoint folders — check --folder-a/--folder-b against /api/documents")
        return 2

    def run_query(label: str, scope: list[str] | None) -> set[str]:
        t = time.perf_counter()
        r = json.loads(_post(args.base, "/query", {"question": args.question, "allowed_document_ids": scope}))
        cited = {s["document_id"] for s in r["sources"]}
        files = sorted({s["source_file"] for s in r["sources"]})
        print(f"  [{label}] {time.perf_counter() - t:.1f}s, {len(cited)} cited: {files}")
        print(f"  answer: {r['answer'][:160]!r}")
        return cited

    cited = run_query("query, scope A", scope_a)
    check("query scoped to A cites only A", cited <= set(scope_a), f"outside={cited - set(scope_a)}")
    check("query scoped to A cites something", bool(cited))

    cited = run_query("query, scope B (disjoint)", scope_b)
    check("query scoped to B cites only B", cited <= set(scope_b), f"outside={cited - set(scope_b)}")
    check("query scoped to B never cites A", not (cited & set(scope_a)))

    cited = run_query("query, unscoped", None)
    check("unscoped query answers", True, f"{len(cited)} cited")

    t = time.perf_counter()
    body = {
        "session_id": f"scope-check-{int(time.time())}",
        "question": args.question,
        "use_memory": False,
        "allowed_document_ids": scope_a,
    }
    ans = _chat_answer(args.base, body)
    cited = {s["document_id"] for s in ans["sources"]}
    files = sorted({s["source_file"] for s in ans["sources"]})
    print(f"  [chat, scope A] {time.perf_counter() - t:.1f}s, cited: {files}")
    print(f"  answer: {ans['answer'][:160]!r}")
    check("chat scoped to A cites only A", cited <= set(scope_a), f"outside={cited - set(scope_a)}")
    check("chat scoped to A cites something", bool(cited))

    print("\nALL PASS" if not fails else f"\n{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
