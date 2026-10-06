"""Entity and relationship extraction from document chunks using the LLM.

Ported from raggles. Runs at ingest time (worker stage "extracting_graph"):
every chunk is shown to the LLM with a prompt tuned for technical/industrial
documents, yielding entities (controllers, sensors, protocols...) and typed
relationships ("uses", "compatible_with", ...). Entity names are then batch
embedded so retrieval-time entity matching can use cosine similarity.

Uses llm.complete + manual JSON parsing (not complete_json) deliberately:
a malformed response for one chunk should degrade to "no entities from this
chunk", never retry loops or batch failure.
"""

import asyncio
import json
import re

import structlog

from ragline.chunking.models import Chunk
from ragline.config import settings
from ragline.embeddings.base import BaseEmbedder
from ragline.llm.base import BaseLLM

log = structlog.get_logger()

# Global semaphore shared across ALL concurrent document extractions, so a
# 3-document batch can't stack 3x the configured LLM concurrency.
_llm_semaphore = asyncio.Semaphore(settings.kg_extraction_concurrency)

# Extraction prompt — tuned for technical documentation. Doubled braces are
# literal braces in str.format.
EXTRACT_PROMPT = """\
Extract entities and relationships from the following technical document chunk.

Entities are named things like: products, sensors, controllers, modules, protocols, \
standards, components, tools, or technical concepts.

Relationships describe how entities relate to each other: "uses", "compatible_with", \
"part_of", "connects_to", "requires", "supports", "replaces", "type_of".

Output a JSON object with:
- "entities": list of {{"name": str, "type": str, "description": str}}
- "relationships": list of {{"source": str, "target": str, "relation": str, "description": str}}

Use canonical names (e.g., "M580" not "the M580 controller"). Keep descriptions brief (one sentence).
Output ONLY valid JSON, no explanation.

---
Document: {source_file}
Section: {section_header}
---
{chunk_text}"""


async def extract_entities_and_relationships(
    chunks: list[Chunk],
    llm: BaseLLM,
    embedder: BaseEmbedder | None = None,
) -> tuple[list[dict], list[dict]]:
    """Extract entities and relationships from chunks.

    Returns (entities, relationships) as lists of dicts ready for store.py.
    """
    all_entities = []
    all_relationships = []

    async def _extract_one(chunk: Chunk) -> tuple[list[dict], list[dict]]:
        """Extract from a single chunk under the shared concurrency cap."""
        async with _llm_semaphore:
            try:
                # Cap chunk text at 2000 chars — plenty of signal, bounded cost.
                prompt = EXTRACT_PROMPT.format(
                    source_file=chunk.source_file,
                    section_header=chunk.section_header or "N/A",
                    chunk_text=chunk.text[:2000],
                )
                messages = [{"role": "user", "content": prompt}]
                # Cap the output: a chunk that sends the model into a repetition
                # loop would otherwise occupy one of the (now 96) concurrency
                # slots for minutes. A truncated reply is invalid JSON and falls
                # through to the parse-failure branch below — same as any other
                # malformed response, so the document still completes.
                raw = await llm.complete(
                    messages,
                    temperature=0.0,
                    max_tokens=settings.kg_extraction_max_tokens,
                )

                # Strip markdown code fences if the model added them.
                stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
                stripped = re.sub(r"\n?```\s*$", "", stripped)

                data = json.loads(stripped)
                entities = data.get("entities", [])
                relationships = data.get("relationships", [])

                # Stamp provenance: which document/chunk each item came from.
                for ent in entities:
                    ent["document_id"] = chunk.document_id
                    ent["chunk_index"] = chunk.chunk_index

                for rel in relationships:
                    rel["document_id"] = chunk.document_id

                return entities, relationships

            except (json.JSONDecodeError, TypeError) as e:
                # Malformed JSON from the model — skip this chunk quietly.
                log.warning(
                    "entity extraction parse failed",
                    chunk_index=chunk.chunk_index,
                    error=str(e),
                )
                return [], []
            except Exception as e:
                # Any other failure (network etc.) also degrades per-chunk.
                log.warning(
                    "entity extraction failed",
                    chunk_index=chunk.chunk_index,
                    error=str(e),
                )
                return [], []

    # All chunks in parallel, bounded by the semaphore.
    results = await asyncio.gather(*[_extract_one(chunk) for chunk in chunks])
    for entities, relationships in results:
        all_entities.extend(entities)
        all_relationships.extend(relationships)

    # Batch-embed unique entity names so graph_index can match query terms
    # to entities by cosine similarity at retrieval time.
    if embedder and all_entities:
        try:
            unique_names = list({e["name"] for e in all_entities})
            name_embeddings = await embedder.embed(unique_names)
            name_to_embedding = dict(zip(unique_names, name_embeddings))
            for entity in all_entities:
                vec = name_to_embedding.get(entity["name"])
                if vec is not None:
                    # Stored as JSON text in the SQLite column.
                    entity["embedding"] = json.dumps(vec)
        except Exception as e:
            # Without embeddings, graph matching falls back to substrings.
            log.warning("entity name embedding failed", error=str(e))

    log.info(
        "entity extraction complete",
        entities=len(all_entities),
        relationships=len(all_relationships),
    )
    return all_entities, all_relationships
