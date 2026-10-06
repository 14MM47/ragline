"""Structured output schema for the single-call pre-pass.

Ported verbatim from raggles. The pre-pass LLM returns this JSON in one call:
routing mode, a standalone rewrite of the query, plus any exclusions and
document hints it detected — replacing separate rewrite/classify/guardrail
passes.
"""

from typing import Literal

from pydantic import BaseModel, Field


class PrePassResult(BaseModel):
    # Routing: answer from metadata only / both pipelines / normal RAG.
    mode: Literal["library", "compound", "retrieval"] = "retrieval"
    # The query rewritten as a standalone retrieval query (pronouns resolved).
    rewritten_query: str
    # Source filenames the user asked to exclude ("ignoring the ABB manual").
    excluded_sources: list[str] = Field(default_factory=list)
    # Document names/keywords the user is referring to (e.g. ["M580"]).
    target_document_hints: list[str] = Field(default_factory=list)
    # True when the user wants something different/new/alternative.
    has_contrastive_intent: bool = False
    # True when the ask spans the whole collection.
    is_collection_wide: bool = False
