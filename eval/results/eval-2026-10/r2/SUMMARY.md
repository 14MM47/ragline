# eval-2026-10 — rung r2: RedHatAI/Qwen3.8-27B-INT4

Generated 2026-10-15T14:14:33+00:00. Recorded baseline; the 24 GB tier. Must reproduce the known source-hit range before any other rung runs.

| Condition | Path | Repeats | Source hit | Correct (judge) | Recall@8 | Latency median s | Tokens/run | Reasoning chars/run | Think residue | Errors | q/min @1/4/8 | Exit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| off | chat | 3 | 0.774 | 0.681 | 0.917 | 11.267 | 566182.333 | 0.0 | 0 | 0 | 4.69 / 6.94 / 6.79 | None |
| on | chat | 3 | 0.716 | 0.711 | 0.919 | 25.135 | 715769.0 | 508695.0 | 0 | 0 | 1.59 / 3.52 / 6.42 | 0 |
| off-rag | rag | 1 | 0.736 | 0.622 | 0.88 | 12.365 | 465630.0 | 0.0 | 0 | 0 | — | 0 |

## Pod sessions

| Profile | Boot s | Source | Steps (s after POD UP) |
|---|---|---|---|
| eval-r2-qwen3.8-27b-int4 | 868.5 | podlink | up_requested 0.0, created 4.5, running 244.6, healthy_embedder 507.7, healthy_reranker 579.7, healthy_llm 730.2, services_healthy 730.2, stack_test 759.3, client_env_written 868.5, ready 868.5 |

## Spend

- this rung: $10.44 (4.19 h of pod time at the live rate)
- campaign to date: $35.2937 of the $300 cap (stop-and-ask at $250)

## Gate

Review the table and the judge files, then start the next rung with `python scripts/eval_campaign.py eval/campaign/eval-2026-10.toml --rung <next>`. Nothing starts by itself.
