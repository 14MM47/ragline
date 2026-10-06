"""Knowledge graph — LLM-extracted entity/relationship graph over the corpus.

Built at ingest time (extractor), stored in SQLite (models/store), and used
at query time via a NetworkX index (graph_index) whose context is injected
into the answer prompt scoped to the retrieved documents.
"""
