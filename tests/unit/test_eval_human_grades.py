"""scripts/eval_human_grades.py — expanding the hand-graded table.

Loads the script as a module (same pattern as test_evaluate_host_mask.py) and
checks the three parsing rules on a small synthetic table: id ranges and
lists expand, grade counts are cross-checked, and the legend maps to the
judge's scale. No files from eval/results are read here.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_human_grades.py"
spec = importlib.util.spec_from_file_location("eval_human_grades", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TABLE = """# heading

| id | cat | grade | note |
|---|---|---|---|
| A01 | spec | A | abstained |
| A02–A04 | spec | C ×3 | exact values |
| A05 | comp | **W** | wrong column |
| B01, B02 | comp | C ×2 | |
| B03 | spec | C- | minor deviation |
| B04 | spec | N | near miss |

## next section
"""


def test_ids_expand():
    """Single ids, en-dash ranges and comma lists all expand."""
    assert mod.expand_ids("A01") == ["A01"]
    assert mod.expand_ids("A02–A08") == [f"A{n:02d}" for n in range(2, 9)]
    assert mod.expand_ids("A02-A03") == ["A02", "A03"]
    assert mod.expand_ids("D11, D12") == ["D11", "D12"]


def test_bad_id_cell_raises():
    """A typo in the table fails loudly rather than vanishing."""
    with pytest.raises(ValueError):
        mod.expand_ids("A2")
    with pytest.raises(ValueError):
        mod.expand_ids("A01–B03")


def test_grade_cells_parse():
    """Counts, bold markers and the C- grade are all understood."""
    assert mod.parse_grade("C ×7") == ("C", 7)
    assert mod.parse_grade("**W**") == ("W", None)
    assert mod.parse_grade("C-") == ("C-", None)
    with pytest.raises(ValueError):
        mod.parse_grade("B")


def test_table_expands_and_maps():
    """The synthetic table yields one row per question on the judge's scale."""
    rows = mod.parse_table(TABLE)
    assert [r["id"] for r in rows] == ["A01", "A02", "A03", "A04", "A05", "B01", "B02", "B03", "B04"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["A01"]["label"] == "abstained"
    assert by_id["A03"]["label"] == "correct" and by_id["A03"]["note"] == "exact values"
    assert by_id["A05"]["label"] == "wrong" and by_id["A05"]["human_grade"] == "W"
    # The user's mapping: a minor deviation is partial, a labelled near-miss is wrong.
    assert by_id["B03"]["label"] == "partial" and by_id["B03"]["human_grade"] == "C-"
    assert by_id["B04"]["label"] == "wrong" and by_id["B04"]["human_grade"] == "N"
    # "comp" in the table becomes the golden set's category name.
    assert by_id["A05"]["category"] == "comparison"


def test_count_mismatch_raises():
    """A ×N that disagrees with the id range is an error."""
    bad = TABLE.replace("| A02–A04 | spec | C ×3 |", "| A02–A04 | spec | C ×4 |")
    with pytest.raises(ValueError):
        mod.parse_table(bad)


def test_main_writes_json(tmp_path):
    """End to end: the CLI writes the JSON document with the mapping recorded."""
    src = tmp_path / "analysis.md"
    src.write_text(TABLE)
    out = tmp_path / "grades.json"
    assert mod.main([str(src), "-o", str(out), "--expect", "9"]) == 0
    doc = json.loads(out.read_text())
    assert len(doc["grades"]) == 9
    assert doc["mapping"]["W"] == "wrong"
    # A wrong --expect is a non-zero exit, not a silent write.
    assert mod.main([str(src), "-o", str(out), "--expect", "8"]) == 1
