"""Citations — the hard programmatic citation chain.

The LLM only ever emits opaque [Source N] markers; ALL source identity
(file, page, section, document id, quote) is carried programmatically from
the retrieved chunks and re-attached after parsing. The LLM cannot invent,
alter, or misattribute a citation's metadata — at worst it picks the wrong
source number, which the realignment heuristic then corrects.
"""
