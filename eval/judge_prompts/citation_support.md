# Judge task: citation support (v1, 2026-10-13)

You are checking whether the sources an answer cites are actually the ones
its content comes from. For each item you get the system's answer, the
citations it made (source file and page), and the passage behind each
citation.

For each citation say whether the answer uses information from that passage
(`used: true`) or cites it without drawing on it — decorative, mismatched, or
pointing at a passage that does not contain what the answer attributes to it
(`used: false`).

Return JSON only: one entry per item id with one verdict per citation, in the
order given.
