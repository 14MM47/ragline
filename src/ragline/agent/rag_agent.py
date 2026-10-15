"""RAGAgent — retrieve, augment with graph context, generate, extract citations.

Ported from raggles with all playground branches removed (adaptive depth,
step-back, context compression, guardrails, FLARE, Self-RAG, agentic graph).
The surviving flow is raggles' default path:

    retrieve (hybrid + rerank) -> sandwich reorder -> graph context (scoped
    to retrieved docs) -> prompt with numbered [Source i] blocks -> complete
    -> extract_citations

The chunk list built here is THE list citations index into — it is passed to
both format_sources_prompt and extract_citations in identical order.
"""

import structlog

from ragline.agent.prompts import QUERY_TEMPLATE, SYSTEM_PROMPT
from ragline.citations.models import CitedResponse
from ragline.citations.postprocessor import extract_citations
from ragline.citations.prompt_based import format_sources_prompt
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.knowledge_graph.store import get_graph_context_for_query_scoped
from ragline.llm.base import BaseLLM
from ragline.retrieval.pipeline import RetrievalPipeline
from ragline.retrieval.reorder import sandwich_reorder
from ragline.tracing.collector import get_current_trace, timed_step

log = structlog.get_logger()


class RAGAgent:
    def __init__(self, retrieval: RetrievalPipeline, llm: BaseLLM, embedder: BaseEmbedder | None = None):
        self._retrieval = retrieval
        self._llm = llm
        # Embedder is used for graph-context entity matching.
        self._embedder = embedder

    async def query(
        self,
        question: str,
        allowed_document_ids: list[str] | None = None,
        excluded_source_files: list[str] | None = None,
        conversation_context: str = "",
        retrieval_query: str | None = None,
        entity_queries: list[str] | None = None,
    ) -> CitedResponse:
        """Answer one question with hard citations.

        `question` is what the answer prompt asks (the user's question, made
        standalone); `retrieval_query` is what is searched (the pre-pass's
        keyword rewrite) and defaults to the question. With two or more
        `entity_queries` (a question naming several products) each product is
        retrieved separately and given reserved context slots.
        """
        trace = get_current_trace()
        search = retrieval_query or question

        # --- retrieve ------------------------------------------------------
        multi = settings.entity_slots > 0 and bool(entity_queries) and len(entity_queries) >= 2
        if multi:
            results = await self._retrieval.retrieve_multi(
                search,
                entity_queries,
                allowed_document_ids=allowed_document_ids,
                excluded_source_files=excluded_source_files,
            )
        else:
            results = await self._retrieval.retrieve(
                search,
                allowed_document_ids=allowed_document_ids,
                excluded_source_files=excluded_source_files,
            )
        # Lost-in-the-middle mitigation: best chunks at both prompt edges. Not
        # for a multi-product context: it is grouped by product, not ranked.
        if settings.enable_context_reordering and not multi:
            results = sandwich_reorder(results)
        # Continuations of cut tables / numbered steps go straight after their parent.
        with timed_step("neighbours"):
            results = await self._retrieval.expand_neighbours(results)
        # THE chunk list — prompt numbering and citation extraction both
        # index into this exact list.
        chunks = [r.chunk for r in results]

        if not chunks:
            # Nothing retrieved: honest empty-handed answer, zero citations.
            return CitedResponse(
                spans=[],
                sources_used=[],
                query=question,
                model_used=self._llm.model if hasattr(self._llm, "model") else "unknown",
                raw_text="I couldn't find any relevant information in the document library to answer this question.",
            )

        # --- graph context scoped to the retrieved documents ---------------
        graph_context = ""
        used_graph = False
        try:
            doc_ids = list({c.document_id for c in chunks if c.document_id})
            if settings.enable_knowledge_graph:
                with timed_step("graph"):
                    graph_context = await get_graph_context_for_query_scoped(
                        search, doc_ids, embedder=self._embedder
                    )
            if graph_context:
                used_graph = True
                log.info("graph context found", query=question[:80], graph_items=graph_context.count("\n"))
        except Exception as e:
            # Graph failure degrades to a plain RAG answer.
            log.warning("graph context lookup failed", error=str(e))

        # --- build the prompt ----------------------------------------------
        sources_text = format_sources_prompt(chunks)
        # Conversation memory (when chat passes it) precedes everything.
        context_block = (
            f"Previous conversation context:\n{conversation_context}\n\n"
            if conversation_context
            else ""
        )
        graph_block = f"{graph_context}\n\n" if graph_context else ""
        user_message = context_block + graph_block + QUERY_TEMPLATE.format(query=question, sources=sources_text)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        # --- generate ------------------------------------------------------
        with timed_step("answer"):
            # answer=True: answer-only request options (e.g. thinking) apply here.
            raw_text = await self._llm.complete(messages, max_tokens=settings.answer_max_tokens, answer=True,
                                              purpose="answer")

        # --- extract citations ---------------------------------------------
        model_name = self._llm.model if hasattr(self._llm, "model") else "unknown"
        with timed_step("citations"):
            cited_response = extract_citations(raw_text, chunks, question, model_name)

        # Record answer-level facts on the trace (token totals accumulate
        # automatically inside the provider).
        if trace:
            trace.record_response(
                citation_count=len(cited_response.sources_used),
                source_files=list({s.source_file for s in cited_response.sources_used}),
            )
        cited_response.used_graph = used_graph

        log.info(
            "query complete",
            question=question[:80],
            sources_used=len(cited_response.sources_used),
            used_graph=used_graph,
        )
        return cited_response
