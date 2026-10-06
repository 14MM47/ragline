"""Knowledge graph storage and query operations.

Ported from raggles minus the entity-dedup/community branches. The main
retrieval-time entry point is get_graph_context_for_query_scoped(): given the
user's query and the document ids that retrieval just returned, it finds
matching entities and walks the graph 2 hops out, formatting the neighborhood
as a text block the RAG agent appends to the prompt.
"""

import structlog
from sqlalchemy import or_, select

from ragline.embeddings.base import BaseEmbedder
from ragline.knowledge_graph.models import Entity, Relationship
from ragline.storage.metadata_db import _async_session

log = structlog.get_logger()


async def save_entities(entities: list[dict]) -> list[Entity]:
    """Save extracted entities, deduplicating by name within the same document."""
    saved = []
    if not entities:
        return saved

    async with _async_session() as session:
        # One query for ALL existing entities in the affected documents, keyed
        # by (name, document_id) — instead of a SELECT per entity (N+1).
        doc_ids = {ent["document_id"] for ent in entities}
        result = await session.execute(
            select(Entity).where(Entity.document_id.in_(doc_ids))
        )
        by_key: dict[tuple[str, str], Entity] = {
            (e.name, e.document_id): e for e in result.scalars().all()
        }

        for ent in entities:
            # Same name in the same document = same entity (mentions from
            # different chunks collapse to one row). by_key also absorbs
            # duplicates within THIS batch.
            key = (ent["name"], ent["document_id"])
            existing = by_key.get(key)
            if existing:
                saved.append(existing)
                continue

            entity = Entity(
                name=ent["name"],
                entity_type=ent.get("type", ""),
                document_id=ent["document_id"],
                chunk_index=ent.get("chunk_index", 0),
                description=ent.get("description", ""),
                embedding=ent.get("embedding", ""),
            )
            session.add(entity)
            by_key[key] = entity
            saved.append(entity)
        await session.commit()
    return saved


async def save_relationships(relationships: list[dict], entities: list[Entity]) -> None:
    """Save extracted relationships, resolving entity names to row IDs."""
    # Case-insensitive name -> entity lookup (first match wins).
    name_to_entity: dict[str, Entity] = {}
    for ent in entities:
        key = ent.name.lower()
        if key not in name_to_entity:
            name_to_entity[key] = ent

    async with _async_session() as session:
        for rel in relationships:
            source = name_to_entity.get(rel["source"].lower())
            target = name_to_entity.get(rel["target"].lower())
            # Relationships naming unknown entities are dropped silently —
            # the extractor sometimes references entities it didn't list.
            if not source or not target:
                continue

            relationship = Relationship(
                source_entity_id=source.id,
                target_entity_id=target.id,
                relation_type=rel.get("relation", ""),
                document_id=rel["document_id"],
                description=rel.get("description", ""),
            )
            session.add(relationship)
        await session.commit()


async def get_related_entities(entity_ids: list[str], max_hops: int = 2) -> list[dict]:
    """SQL-only graph walk up to max_hops (fallback when no GraphIndex).

    Slower than the NetworkX path (per-hop queries) but dependency-free.
    """
    if not entity_ids:
        return []

    visited = set(entity_ids)
    context_items = []

    current_ids = set(entity_ids)

    async with _async_session() as session:
        for hop in range(max_hops):
            if not current_ids:
                break

            # All relationships touching the current frontier.
            conditions = []
            for eid in current_ids:
                conditions.append(Relationship.source_entity_id == eid)
                conditions.append(Relationship.target_entity_id == eid)

            result = await session.execute(
                select(Relationship).where(or_(*conditions))
            )
            rels = list(result.scalars().all())

            # Collect this hop's newly-discovered (neighbor_id, edge) pairs.
            next_ids = set()
            discovered: list[tuple[str, Relationship]] = []
            for rel in rels:
                # Follow the edge to whichever side isn't the frontier node.
                other_id = rel.target_entity_id if rel.source_entity_id in current_ids else rel.source_entity_id
                if other_id not in visited:
                    visited.add(other_id)
                    next_ids.add(other_id)
                    discovered.append((other_id, rel))

            # Materialize ALL discovered entities in ONE query (not one per
            # neighbor — that was an N+1 inside the per-hop loop).
            if discovered:
                ent_result = await session.execute(
                    select(Entity).where(Entity.id.in_({oid for oid, _ in discovered}))
                )
                entity_by_id = {e.id: e for e in ent_result.scalars().all()}
                for other_id, rel in discovered:
                    other_entity = entity_by_id.get(other_id)
                    if other_entity:
                        context_items.append({
                            "entity": other_entity.name,
                            "entity_type": other_entity.entity_type,
                            "relation": rel.relation_type,
                            "description": rel.description or other_entity.description,
                            "hop": hop + 1,
                        })

            current_ids = next_ids

    return context_items


def _format_graph_context(related: list[dict]) -> str:
    """Format discovered graph neighbors as the prompt-injectable block."""
    lines = ["Related knowledge graph context:"]
    # Cap at 10 items — graph context supplements chunks, never dominates.
    for item in related[:10]:
        lines.append(
            f"- {item['entity']} ({item['entity_type']}): "
            f"{item['relation']} — {item['description']}"
        )
    return "\n".join(lines)


async def get_graph_context_for_query_scoped(
    query: str,
    document_ids: list[str],
    embedder: BaseEmbedder | None = None,
) -> str:
    """Graph context scoped to the documents retrieval just returned.

    Preferred path: embedding-based entity matching + NetworkX BFS via
    GraphIndex. Fallback (no embedder / index failure): substring matching
    against entity names + the SQL walk above. Returns "" when the graph has
    nothing relevant — the agent simply omits the block.
    """
    if not document_ids:
        return ""

    if embedder is not None:
        try:
            from ragline.knowledge_graph.graph_index import GraphIndex

            # Build a small in-memory graph over just the retrieved documents.
            graph_index = GraphIndex()
            await graph_index.build_from_db(document_ids=document_ids)
            matched = await graph_index.find_entities(query, embedder, top_k=5)
            if not matched:
                return ""
            entity_ids = [e.id for e in matched]
            related = graph_index.get_subgraph(entity_ids, max_hops=2)
            if not related:
                return ""
            return _format_graph_context(related)
        except Exception as e:
            log.warning("graph index query failed, falling back to substring", error=str(e))

    # Fallback: entity names appearing verbatim in the query.
    async with _async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.document_id.in_(document_ids))
        )
        scoped_entities = list(result.scalars().all())

    if not scoped_entities:
        return ""

    query_lower = query.lower()
    matched_entities = [
        ent for ent in scoped_entities if ent.name.lower() in query_lower
    ]

    if not matched_entities:
        return ""

    entity_ids = [e.id for e in matched_entities]
    related = await get_related_entities(entity_ids, max_hops=2)

    if not related:
        return ""

    return _format_graph_context(related)


async def delete_entities_by_document(document_id: str) -> None:
    """Remove all entities and relationships for a deleted document."""
    async with _async_session() as session:
        # Relationships first, then entities.
        result = await session.execute(
            select(Relationship).where(Relationship.document_id == document_id)
        )
        for rel in result.scalars().all():
            await session.delete(rel)

        result = await session.execute(
            select(Entity).where(Entity.document_id == document_id)
        )
        for ent in result.scalars().all():
            await session.delete(ent)

        await session.commit()
