"""format_for_api — serialize a CitedResponse for the JSON/SSE wire format.

Ported from raggles plus the original_path field on each source.
"""

from ragline.citations.models import CitedResponse


def format_for_api(response: CitedResponse) -> dict:
    """Format CitedResponse for the API response."""
    return {
        # The full raw answer text (spans reassemble it with citations).
        "answer": response.raw_text,
        "spans": [
            {"text": span.text, "citation_ids": span.citation_ids} for span in response.spans
        ],
        "sources": [
            {
                "citation_id": c.citation_id,
                "source_file": c.source_file,
                "page_number": c.page_number,
                "section": c.section,
                "quoted_text": c.quoted_text,
                "document_id": c.document_id,
                # Provenance: the original network location ("" when unknown).
                "original_path": c.original_path,
            }
            for c in response.sources_used
        ],
        "query": response.query,
        "model_used": response.model_used,
        "used_graph": response.used_graph,
    }
