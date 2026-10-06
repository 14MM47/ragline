"""Knowledge graph models — lightweight entity-relationship storage in SQLite.

Ported from raggles minus the Community table (community detection is a
roadmap item; its schema can be re-added from raggles when wanted).

The document_id + chunk_index columns are deliberately retained on both
tables: they are the join that will power the future visual graph explorer's
"which documents mention this entity?" queries — do not strip them.
"""

import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


class Entity(SQLModel, table=True):
    """A named entity extracted from documents (e.g. sensor model, controller, protocol)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    # Canonical display name, e.g. "M580", "Ethernet/IP".
    name: str = Field(index=True)
    # Coarse type tag, e.g. "controller", "sensor", "protocol", "module".
    entity_type: str = ""
    # Which document and chunk this mention was extracted from — the
    # provenance join used at retrieval (doc-scoped graph context) and by the
    # future graph explorer.
    document_id: str = Field(index=True)
    chunk_index: int = 0
    # One-line description produced by the extraction LLM.
    description: str = ""
    # JSON-serialized embedding of the entity name, used for similarity
    # matching between query terms and entities at retrieval time.
    embedding: str = ""
    # Reserved for future cross-document dedup: points at the canonical
    # entity when this row is judged a duplicate (unused in v1).
    canonical_entity_id: Optional[str] = Field(default=None, index=True)


class Relationship(SQLModel, table=True):
    """A directed relationship between two entities (e.g. "M580 uses Ethernet/IP")."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_entity_id: str = Field(index=True)
    target_entity_id: str = Field(index=True)
    # Relation label, e.g. "uses", "compatible_with", "part_of", "connects_to".
    relation_type: str = ""
    # Document the relationship was stated in (provenance).
    document_id: str = Field(index=True)
    # Natural-language statement, e.g. "M580 uses Ethernet/IP for communication".
    description: str = ""
