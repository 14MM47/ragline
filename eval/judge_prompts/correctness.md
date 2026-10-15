# Judge task: correctness (v1, 2026-10-13)

You are grading answers produced by a document question-answering system over
industrial HMI vendor datasheets and manuals. For each item you get the
question, the reference answer written by a human from the documents, verbatim
evidence quotes with their source file and page, and the system's answer.

Grade ONLY whether the system's answer gives the asked-for information
correctly. Ignore style, length and extra context unless it contradicts the
reference. Judge against the evidence quotes, not against your own knowledge:
if the answer and the reference differ, the evidence decides.

Verdicts:

- `correct` — the asked-for value(s) are given with the right units (or the
  asked-for steps in the right order, or the comparison names both values and
  the right winner). Extra context is fine. Equivalent units or rounding that
  keeps the stated precision are fine (8.4 W and 8.40 W; 2.5 kg and 2500 g).
- `partial` — the right value with a minor deviation: lost precision (8 W for
  8.4 W), a missing unit, one side of a comparison missing, a step list with
  one step missing or out of order, or the right value hedged as uncertain.
- `wrong` — a different value, product or answer. This INCLUDES an honestly
  labelled value for a sibling model ("the DOP-107BV draws 5.8 W, the 107WV
  is not listed"): a near-miss is wrong even when close and labelled.
- `abstained` — the answer says the information is not available, not
  stated, or not found, and gives no value. (For `unanswerable` items this is
  the desired behaviour: use `abstained` when the answer declines or says the
  documents do not state it; use `wrong` when it supplies a value or asserts
  a yes/no that the documents do not support.)

Comparison questions need BOTH values and the right direction for `correct`;
one correct value and a wrong or missing other is `partial`; the wrong
direction is `wrong`.

Return JSON only, one entry per item id, with a one-sentence reason that
names the value(s) you compared.
