"""In-memory graph index for efficient entity matching and traversal.

Ported from raggles minus the entity-dedup filter. Loads entities and
relationships from SQLite with 2 bulk queries into a NetworkX graph, matches
query text to entities by embedding cosine similarity, and walks the
neighborhood with O(V+E) BFS. Rebuildable purely from SQLite — a property
the future visual graph explorer will rely on.
"""

import json

import networkx as nx
import numpy as np
import structlog
from sqlalchemy import select

from ragline.embeddings.base import BaseEmbedder
from ragline.knowledge_graph.models import Entity, Relationship
from ragline.storage.metadata_db import _async_session

log = structlog.get_logger()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Plain cosine similarity with a zero-norm guard."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


class GraphIndex:
    """In-memory graph with embedding-based entity lookup and BFS traversal."""

    def __init__(self):
        # Undirected graph of entity ids; edges carry relation metadata.
        self._graph = nx.Graph()
        self._entities: dict[str, Entity] = {}                     # id -> Entity
        self._entity_embeddings: dict[str, np.ndarray] = {}        # id -> vector
        self._relationship_data: dict[tuple[str, str], dict] = {}  # (src, tgt) -> metadata

    async def build_from_db(self, document_ids: list[str] | None = None) -> None:
        """Load entities and relationships into the NetworkX graph.

        Uses 2 bulk SQL queries (not N+1). When document_ids is given the
        graph is scoped to just those documents (the retrieval-time case).
        """
        async with _async_session() as session:
            # Bulk query 1: entities (optionally scoped).
            if document_ids:
                stmt = select(Entity).where(Entity.document_id.in_(document_ids))
            else:
                stmt = select(Entity)
            result = await session.execute(stmt)
            entities = list(result.scalars().all())

            entity_ids = {e.id for e in entities}

            # Bulk query 2: relationships touching any loaded entity.
            if entity_ids:
                result = await session.execute(
                    select(Relationship).where(
                        Relationship.source_entity_id.in_(entity_ids)
                        | Relationship.target_entity_id.in_(entity_ids)
                    )
                )
                relationships = list(result.scalars().all())
            else:
                relationships = []

        # Materialize nodes (+ pre-computed name embeddings when present).
        for entity in entities:
            self._entities[entity.id] = entity
            self._graph.add_node(entity.id, name=entity.name, entity_type=entity.entity_type)

            if entity.embedding:
                try:
                    vec = json.loads(entity.embedding)
                    self._entity_embeddings[entity.id] = np.array(vec, dtype=np.float32)
                except (json.JSONDecodeError, ValueError):
                    # Corrupt embedding just means substring fallback for
                    # this entity — never a build failure.
                    pass

        # Materialize edges; both endpoints must be loaded.
        for rel in relationships:
            if rel.source_entity_id in entity_ids and rel.target_entity_id in entity_ids:
                self._graph.add_edge(
                    rel.source_entity_id,
                    rel.target_entity_id,
                    relation=rel.relation_type,
                    description=rel.description,
                )
                self._relationship_data[(rel.source_entity_id, rel.target_entity_id)] = {
                    "relation": rel.relation_type,
                    "description": rel.description,
                }

        log.info(
            "graph index built",
            entities=len(entities),
            relationships=len(relationships),
            has_embeddings=len(self._entity_embeddings),
        )

    async def find_entities(
        self,
        query: str,
        embedder: BaseEmbedder,
        top_k: int = 5,
        threshold: float = 0.5,
    ) -> list[Entity]:
        """Find entities matching the query using embedding similarity.

        Falls back to substring matching if no entity embeddings are loaded.
        """
        if not self._entities:
            return []

        # Preferred: cosine similarity between the query and entity names.
        if self._entity_embeddings:
            # Raw query (instruction=""): entity names are embedded unprefixed
            # and `threshold` was calibrated on raw-vs-raw cosine scores.
            query_embedding = np.array(
                await embedder.embed_query(query, instruction=""), dtype=np.float32
            )
            scored: list[tuple[float, str]] = []
            for eid, emb in self._entity_embeddings.items():
                sim = _cosine_similarity(query_embedding, emb)
                # Below-threshold matches are noise, not signal.
                if sim >= threshold:
                    scored.append((sim, eid))

            scored.sort(reverse=True)
            return [self._entities[eid] for _, eid in scored[:top_k]]

        # Fallback: entity name appears verbatim in the query.
        query_lower = query.lower()
        return [
            ent for ent in self._entities.values()
            if ent.name.lower() in query_lower
        ][:top_k]

    def get_subgraph(self, entity_ids: list[str], max_hops: int = 2) -> list[dict]:
        """BFS traversal from seed entities, returning related entities with context.

        O(V+E) via NetworkX BFS instead of O(V*H) individual SQL queries.
        """
        if not entity_ids:
            return []

        visited: set[str] = set()
        context_items: list[dict] = []
        # Only seeds that actually exist as nodes.
        seeds = set(entity_ids) & set(self._graph.nodes)

        for seed in seeds:
            # Depth-limited BFS from this seed; yields node -> distance.
            for node, depth in nx.single_source_shortest_path_length(
                self._graph, seed, cutoff=max_hops
            ).items():
                # Seeds themselves and already-collected nodes are skipped.
                if node in seeds or node in visited:
                    continue
                visited.add(node)

                entity = self._entities.get(node)
                if not entity:
                    continue

                # Attach the relation that connects this node back toward
                # the seed neighborhood, for a readable context line.
                rel_info = self._find_connecting_relationship(node, seeds | visited)

                context_items.append({
                    "entity": entity.name,
                    "entity_type": entity.entity_type,
                    "relation": rel_info.get("relation", "related_to"),
                    "description": rel_info.get("description", entity.description),
                    "hop": depth,
                })

        return context_items

    def _find_connecting_relationship(
        self, node: str, connected_nodes: set[str]
    ) -> dict:
        """Relationship metadata between a node and any already-connected neighbor."""
        for neighbor in self._graph.neighbors(node):
            if neighbor in connected_nodes:
                # The metadata dict is keyed by insertion order — check both
                # directions since the graph itself is undirected.
                key = (neighbor, node)
                if key in self._relationship_data:
                    return self._relationship_data[key]
                key = (node, neighbor)
                if key in self._relationship_data:
                    return self._relationship_data[key]
        return {}
