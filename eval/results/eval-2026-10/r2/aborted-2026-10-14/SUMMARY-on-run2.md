# eval-2026-10 — rung r2: RedHatAI/Qwen3.8-27B-INT4

Generated 2026-10-14T14:34:50+00:00. Recorded baseline; the 24 GB tier. Must reproduce the known source-hit range before any other rung runs.

| Condition | Path | Repeats | Source hit | Correct (judge) | Recall@8 | Latency median s | Tokens/run | Reasoning chars/run | Think residue | Errors | q/min @1/4/8 | Exit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| off | chat | 3 | 0.774 | 0.681 | 0.917 | 11.267 | 566182.333 | 0.0 | 0 | 0 | 4.69 / 6.94 / 6.79 | None |
| on | chat | 0 | None | None | None | None | None | None | 0 | 0 | — | -15 |
| off-rag | rag | 1 | 0.0 | None | None | 3.12 | 0.0 | 0.0 | 0 | 100 | — | 0 |

## Pod sessions

| Profile | Boot s | Source | Steps (s after POD UP) |
|---|---|---|---|
| eval-r2-qwen3.8-27b-int4 | 947.0 | podlink | up_requested 0.0, created 3.2, running 444.1, healthy_embedder 553.5, healthy_reranker 670.7, healthy_llm 890.4, services_healthy 890.4, stack_test 927.2, client_env_written 947.0, ready 947.0 |

## Spend

- this rung: $0.0 (0.0 h of pod time at the live rate)
- campaign to date: $20.392 of the $300 cap (stop-and-ask at $250)

## Gate

Review the table and the judge files, then start the next rung with `python scripts/eval_campaign.py eval/campaign/eval-2026-10.toml --rung <next>`. Nothing starts by itself.
