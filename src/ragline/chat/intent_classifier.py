"""Keyword intent classifier — routes queries to library/compound/RAG.

Ported from raggles, keyword variant only (the LLM/embedding classifiers were
playground experiments). With the structured pre-pass enabled the pre-pass
LLM does this classification itself; the keyword classifier covers the
memory-OFF path (no pre-pass runs) so "how many documents do you have?"
still reaches library mode with zero LLM cost.
"""

from abc import ABC, abstractmethod
from enum import Enum

import structlog

log = structlog.get_logger()


class QueryIntent(str, Enum):
    LIBRARY = "library"                # pure document-library metadata query
    COMPOUND = "compound"              # library + content retrieval
    RAG = "rag"                        # standard retrieval-augmented generation
    CONVERSATIONAL = "conversational"  # no retrieval needed (unused by keyword variant)


class IntentClassifier(ABC):
    @abstractmethod
    async def classify(self, query: str) -> tuple[QueryIntent, float]:
        """Return (intent, confidence) for the query."""
        ...


# Phrases that signal the user is asking about the LIBRARY itself.
_LIBRARY_KEYWORDS = [
    "doc library", "document library",
    "what documents", "which documents",
    "list all documents", "list documents", "list all docs", "list docs",
    "what files", "which files", "list all files", "list files",
    "summarise all", "summarize all", "summary of all",
    "summarise the doc", "summarize the doc",
    "summarise the lib", "summarize the lib",
    "all the docs", "all the documents", "all the files",
    "all docs", "all documents",
    "what do you have", "what have you got",
    "what's in the library", "what is in the library",
    "how many documents", "how many docs", "how many files",
    "library overview", "library summary",
    "what's available", "what is available",
    "show me all", "show all docs", "show all documents",
]
# A topic qualifier promotes LIBRARY to COMPOUND ("list docs ABOUT sensors").
_TOPIC_QUALIFIERS = [" about ", " regarding ", " related to ", " on the topic of ", " concerning "]
# So does a connector joining two asks.
_COMPOUND_CONNECTORS = [" and ", " also ", " plus ", " as well as "]


class KeywordIntentClassifier(IntentClassifier):
    """Pure keyword matching — instant and free."""

    async def classify(self, query: str) -> tuple[QueryIntent, float]:
        q = query.lower()
        # No library phrase at all -> normal RAG.
        is_library = any(kw in q for kw in _LIBRARY_KEYWORDS)
        if not is_library:
            return QueryIntent.RAG, 1.0

        # Library phrase + topic/connector -> both pipelines.
        has_topic = any(tq in q for tq in _TOPIC_QUALIFIERS)
        has_connector = any(cc in q for cc in _COMPOUND_CONNECTORS)

        if has_topic or has_connector:
            return QueryIntent.COMPOUND, 0.9
        return QueryIntent.LIBRARY, 0.95


def create_intent_classifier(mode: str) -> IntentClassifier:
    """Factory — only the keyword variant exists in ragline."""
    # mode is accepted for config compatibility; anything maps to keyword.
    return KeywordIntentClassifier()
