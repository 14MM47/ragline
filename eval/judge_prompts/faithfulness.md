# Judge task: faithfulness (v1, 2026-10-13)

You are checking whether an answer is grounded in the passages the system
retrieved. For each item you get the question, the system's answer, and the
numbered passages that were in the system's context when it answered.

List the answer's factual claims — each number, specification, product
name, yes/no statement, or step — and for each one say whether it is
supported by a passage (give the passage number) or unsupported (no passage
states it; a passage states something different; or the claim combines
passages in a way they do not support). A statement that the documents do
not contain something is supported when no passage contains it. Hedges and
refusals ("I couldn't find…") carry no claims. Do not use outside knowledge:
only the passages count.

Return JSON only: one entry per item id with its list of claims.
