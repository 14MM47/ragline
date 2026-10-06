"""Tracing — minimal per-query token/latency accounting.

raggles tracked ~100 fields per query (per-stage timings, CRAG verdicts,
cache stats, A/B variants...). ragline keeps only what the product needs:
whole-turn token totals, total latency, citation count, and confidence.
"""
