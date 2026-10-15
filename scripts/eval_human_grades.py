"""eval_human_grades.py — turn the hand-graded analysis table into JSON.

The 2026-09-28 analysis (eval/results/2026-09-28_analysis.md) graded the 46
answerable spec + comparison answers by hand in a markdown table whose rows
compress runs of identical grades ("A02–A08 | C ×7", "D11, D12 | C ×2"). The
judge calibration (evaluation plan, Phase 1 step 1.8) needs one row per
question on the judge's own scale, so this script expands the table once:

    python scripts/eval_human_grades.py eval/results/2026-09-28_analysis.md \\
        -o eval/human_grades_2026-09-28.json

Grade mapping (analysis legend -> judge scale), as decided by the user on
2026-10-13: a minor deviation is not a full mark, and a near-miss is wrong even
when the model labels it honestly, because the asked-for value was not given.
    C      -> correct
    C-     -> partial     (correct with a minor deviation)
    A      -> abstained   (abstained/partial although the answer exists)
    N      -> wrong       (honest near-miss: the sibling model's value, labelled)
    W      -> wrong       (confidently wrong)

The output keeps the original grade and note next to the mapped label so a
reviewer can check the mapping, and the user confirms the file before it is
used. Pure text processing: no ragline imports, no network.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Analysis legend -> the judge's correctness scale (eval_judge.py).
GRADE_TO_LABEL = {"C": "correct", "C-": "partial", "A": "abstained", "N": "wrong", "W": "wrong"}

# A single question id: one letter and two digits (A01 … D12).
_ID = re.compile(r"^[A-Z]\d{2}$")


def expand_ids(cell: str) -> list[str]:
    """Expand an id cell into individual ids.

    Accepts "A01", a range "A02–A08" (en dash or hyphen, same letter), and a
    comma list "D11, D12". Anything else raises so a typo in the table is
    caught here rather than silently dropped.
    """
    ids: list[str] = []
    for part in (p.strip() for p in cell.split(",")):
        # A range: letter + start, dash, (letter +) end.
        m = re.match(r"^([A-Z])(\d{2})\s*[–-]\s*(?:([A-Z]))?(\d{2})$", part)
        if m:
            letter, start, end_letter, end = m.groups()
            if end_letter and end_letter != letter:
                raise ValueError(f"range crosses letters: {part!r}")
            ids.extend(f"{letter}{n:02d}" for n in range(int(start), int(end) + 1))
        elif _ID.match(part):
            ids.append(part)
        else:
            raise ValueError(f"unrecognised id cell: {part!r}")
    return ids


def parse_grade(cell: str) -> tuple[str, int | None]:
    """Parse a grade cell into (grade, count).

    "C ×7" -> ("C", 7); "**W**" -> ("W", None); "C-" -> ("C-", None).
    The count, when given, is cross-checked against the expanded ids.
    """
    text = cell.replace("*", "").strip()           # drop bold markers
    m = re.match(r"^(C-|C|A|N|W)(?:\s*[×x]\s*(\d+))?$", text)
    if not m:
        raise ValueError(f"unrecognised grade cell: {cell!r}")
    grade, count = m.groups()
    return grade, (int(count) if count else None)


def parse_table(markdown: str) -> list[dict]:
    """Extract the per-question grade rows from the analysis markdown.

    Looks for the table whose header is `| id | cat | grade | note |` and
    reads rows until the first non-table line. Returns one dict per question.
    """
    lines = markdown.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if re.match(r"^\|\s*id\s*\|\s*cat\s*\|\s*grade\s*\|", ln))
    except StopIteration:
        raise ValueError("per-question grade table (| id | cat | grade | note |) not found") from None

    rows: list[dict] = []
    for ln in lines[start + 2:]:                   # skip header + separator
        if not ln.startswith("|"):
            break                                  # table ended
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 3:
            raise ValueError(f"short table row: {ln!r}")
        id_cell, category, grade_cell = cells[0], cells[1], cells[2]
        note = cells[3] if len(cells) > 3 else ""
        ids = expand_ids(id_cell)
        grade, count = parse_grade(grade_cell)
        if count is not None and count != len(ids):
            raise ValueError(f"row {id_cell!r}: grade count {count} != {len(ids)} ids")
        for qid in ids:
            rows.append({
                "id": qid,
                "category": {"comp": "comparison"}.get(category, category),
                "human_grade": grade,
                "label": GRADE_TO_LABEL[grade],
                "note": note,
            })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expand the hand-graded analysis table to JSON")
    parser.add_argument("analysis", help="Path to the analysis markdown (e.g. eval/results/2026-09-28_analysis.md)")
    parser.add_argument("-o", "--output", required=True, help="JSON file to write")
    parser.add_argument("--expect", type=int, default=None, help="Fail unless exactly this many rows result")
    args = parser.parse_args(argv)

    rows = parse_table(Path(args.analysis).read_text(encoding="utf-8"))
    rows.sort(key=lambda r: r["id"])
    # Duplicate ids would double-count a question in the calibration.
    dupes = {r["id"] for r in rows if sum(x["id"] == r["id"] for x in rows) > 1}
    if dupes:
        print(f"duplicate ids in table: {sorted(dupes)}", file=sys.stderr)
        return 1
    if args.expect is not None and len(rows) != args.expect:
        print(f"expected {args.expect} rows, got {len(rows)}", file=sys.stderr)
        return 1

    out = Path(args.output)
    out.write_text(json.dumps({
        "source": str(args.analysis),
        "scale": sorted(set(GRADE_TO_LABEL.values())),
        "mapping": GRADE_TO_LABEL,
        "grades": rows,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # A short tally so the caller can eyeball the distribution.
    tally = {label: sum(1 for r in rows if r["label"] == label) for label in sorted(set(GRADE_TO_LABEL.values()))}
    print(f"wrote {out} with {len(rows)} grades: {tally}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
