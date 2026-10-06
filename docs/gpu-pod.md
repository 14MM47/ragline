# Running ragline against a rented GPU pod

ragline itself stays on your machine — the app, Qdrant, the SQLite metadata
and the uploaded files. Only model inference moves to the pod. This page
covers what the pod has to serve, how ragline is pointed at it, the one thing
that forces a re-ingest, and the stacks that have actually been run.

## What the pod has to serve

Three long-lived HTTP services. There is no separate "ingestion model":
ingestion and chat are two request streams into the same three services.

| Service | Used for | API ragline calls |
|---|---|---|
| **LLM** | answers, entity extraction at ingest, the chat pre-pass, memory summaries, confidence scoring | OpenAI `/v1/chat/completions` |
| **Embedder** | chunks at ingest, queries, knowledge-graph entities | OpenAI `/v1/embeddings` |
| **Reranker** | reordering retrieved chunks at query time | TEI `POST /rerank` **or** Cohere-style `POST /v1/rerank` |

Any server that speaks those APIs works. The combinations that have been used
are vLLM for the LLM, Hugging Face TEI or vLLM for the embedder, and TEI or
vLLM for the reranker — all three on one GPU, each on its own port.

Because the weights are loaded once and shared, a heavy ingest and an
interactive chat contend for throughput, not for memory: the cost of running
both at once is latency. `KG_EXTRACTION_CONCURRENCY` (default 20) caps how
many extraction calls an ingest keeps in flight; lowering it leaves batch
slots free for chat.

## Pointing ragline at the pod

Everything is `.env`. The block for a pod reached through RunPod's HTTPS
proxy, with the port layout podlink uses:

```dotenv
# LLM — every LLM call ragline makes
LLM_BASE_URL=https://<pod-id>-8000.proxy.runpod.net/v1
LLM_API_KEY=<pod bearer>
LLM_MODEL=<served model name>          # must equal vLLM's --served-model-name, or requests 404

# Embedder — separate port on the same pod
EMBEDDING_BASE_URL=https://<pod-id>-8080.proxy.runpod.net/v1
EMBEDDING_API_KEY=<pod bearer>
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIMENSIONS=4096
# Qwen3-Embedding only — an instruction prepended to queries (not documents):
EMBEDDING_QUERY_INSTRUCTION=Given a technical question about industrial automation products, retrieve datasheet passages that answer it

# Reranker — the server ROOT; ragline appends /rerank or /v1/rerank itself
RERANKER_PROVIDER=api
RERANKER_BASE_URL=https://<pod-id>-8081.proxy.runpod.net
RERANKER_API_KEY=<pod bearer>
RERANKER_API_FORMAT=cohere             # "tei" for a TEI reranker, "cohere" for vLLM

# Leave room for chat while an ingest is running
KG_EXTRACTION_CONCURRENCY=10
```

Things that go wrong here, in the order they usually do:

- **401 from the embedder or reranker while the LLM works.** On a podlink pod
  all three services are gated with the same bearer, because every port is on
  a public proxy. All three `*_API_KEY` values must be set.
- **404 from the LLM.** `LLM_MODEL` is the *served* name, not the Hugging
  Face repo id.
- **A reranker URL ending in `/rerank`.** Give the root; the path is added
  according to `RERANKER_API_FORMAT`.
- **Stale endpoints.** A pod that is terminated and recreated gets a new id,
  so all three URLs change. The LLM, embedder and reranker clients are built
  once at startup — after editing `.env`, restart ragline.

Check the wiring before doing anything expensive:

```bash
.venv/bin/python scripts/smoke_llm.py        # one completion + one embedding; prints the dimension
curl -s localhost:8000/api/health            # llm / embedder / reranker / qdrant
```

## Changing the embedder means re-ingesting

Vectors of different dimensions cannot share a Qdrant collection, and vectors
from different models are not comparable even at the same dimension. ragline
sizes a collection from the first vector it stores, so a *new* collection
always comes out right — but an existing one is tied to the embedder that
filled it.

When the embedding model or dimension changes, stop ragline and use a new
collection **and a separate SQLite database and storage directory**. Duplicate
detection is global within SQLite: keeping the old database would skip the
same PDFs and leave the new collection empty. The database also contains the
knowledge graph, including entity embeddings tied to the previous embedder.

For example, edit these values in `.env` alongside the new embedding endpoint:

```dotenv
QDRANT_COLLECTION=ragline_embed_experiment
DATABASE_URL=sqlite+aiosqlite:///./data/embed_experiment/ragline.db
UPLOAD_DIR=./data/embed_experiment/uploads
MEMORY_DIR=./data/embed_experiment/memory
```

The SQLite parent directory is created automatically. With Qdrant running,
ingest before restarting the app:

```bash
.venv/bin/python scripts/ingest.py testdata/hmi
./restart.sh
```

Keep the previous collection and data directory. To return to that experiment,
restore its model settings and all four storage settings, then restart.
Changing only the LLM or reranker needs no re-ingest, though the knowledge
graph was extracted by whichever LLM ran the ingest.

## With podlink

[podlink](https://github.com/14MM47/podlink) is a small local web console
that creates the pod, waits for all three services to pass their health
checks, shows the running cost, and tears the pod down again. It is a separate
project and ragline does not require it; what ragline provides is the other
end of podlink's client-env handoff.

Add to the podlink profile:

```bash
export PODLINK_CLIENT_ENV_FILE=~/.config/podlink/ragline.env
export PODLINK_CLIENT_ENV_HOOK=/path/to/ragline/scripts/apply_pod_env.py
export PODLINK_CLIENT_ENV_EXTRA="KG_EXTRACTION_CONCURRENCY=10"
```

When a pod comes up and passes podlink's stack test, podlink writes the block
above (live URLs, bearer, the embedding dimension it measured) and runs the
hook. `scripts/apply_pod_env.py` then:

1. keeps only the keys that belong to pod wiring (`LLM_*`, `EMBEDDING_*`,
   `RERANKER_*`, `KG_EXTRACTION_CONCURRENCY`) — nothing in the block can touch
   auth or storage settings;
2. replaces those lines in `.env` in place, keeping the previous file as
   `.env.bak`;
3. restarts ragline (`./restart.sh` detached, or `systemctl restart ragline`
   where that unit exists) and waits for `/api/health` to report `ok`.

Switching stacks is then: pod down, pick another profile, pod up. To apply a
block by hand, save it to a file and run `scripts/apply_pod_env.py <file>`;
`RAGLINE_APPLY_RESTART=none` merges without restarting.

The hook updates model wiring only. If a new stack uses a different embedder,
stop the app and select a new collection, database and storage directory using
the [procedure above](#changing-the-embedder-means-re-ingesting) before ingesting.

## Without podlink

Start the three services yourself on any GPU host. A minimal version:

```bash
# One bearer gates all three. Pass it by environment, not as a flag (see below).
export VLLM_API_KEY="$BEARER" API_KEY="$BEARER"

# LLM — vLLM, OpenAI-compatible. Cap its share of the card so the other two fit.
vllm serve <LLM_MODEL_ID> \
  --served-model-name ragline-llm \
  --gpu-memory-utilization 0.70 \
  --max-model-len 32768 \
  --port 8000

# Embedder — TEI (exposes OpenAI /v1/embeddings)
text-embeddings-router --model-id <EMBED_MODEL_ID> --port 8080

# Reranker — TEI (/rerank) for encoder rerankers such as BAAI/bge-reranker-v2-m3 ...
text-embeddings-router --model-id <RERANK_MODEL_ID> --port 8081
# ... or a second vLLM (/v1/rerank) for decoder rerankers such as Qwen3-Reranker,
# which TEI does not serve; set RERANKER_API_FORMAT=cohere for this one.
```

Points that cost time when missed:

- **Server logs can leak the bearer.** vLLM logs its non-default command-line
  arguments at startup, so a key given as `--api-key` ends up in the pod's
  logs; use the `VLLM_API_KEY` environment variable. TEI prints its settings
  at startup too — check what your version shows before sharing logs.
  podlink's image handles both; its changelog has the details.

- **`--gpu-memory-utilization` is the co-residency knob.** vLLM pre-allocates
  that fraction of the card for weights and KV cache; the embedder and
  reranker allocate from what is left.
- **The quantisation flag belongs to the model.** An AWQ build, an MXFP4
  build and an INT4 build each need their own settings; do not carry one
  across a model swap.
- **TEI's client batch limit is 32** by default. ragline batches embedding
  and rerank requests to fit; raising TEI's limit is not required.
- **Model downloads dominate a cold start.** Tens of GB of weights on every
  fresh pod, unless they sit on a persistent volume —
  [huggingface.md](huggingface.md) covers tokens, caching and pre-warming.

## Stacks that have been run

| Stack | LLM | Embedder | Reranker | Card | Status |
|---|---|---|---|---|---|
| "balanced" | `stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ` | `Qwen/Qwen3-Embedding-8B` (TEI) | `BAAI/bge-reranker-v2-m3` (TEI) | 1× RTX PRO 6000, 96 GB | Brought up and exercised end to end; no recorded golden-set run |
| "3090" | `RedHatAI/Qwen3.8-27B-INT4`, thinking off | `Qwen/Qwen3-Embedding-8B` (TEI) | `Qwen/Qwen3-Reranker-0.6B` (vLLM) | 1× RTX PRO 6000; 1× RTX A6000, 48 GB | Four recorded runs — [eval/results/](../eval/results/README.md) |

The "3090" stack is sized for a pair of 24 GB cards and has so far been run on
single larger cards standing in for them: the PRO 6000 as an upper bound, the
A6000 as the nearer match (same GPU generation as the 3090, somewhat lower
memory bandwidth).

Open-weight models move quickly. Treat the repo ids above as what was run, not
as recommendations, and check that an id still exists before building on it.

## Cost and lifecycle

- **A running pod bills by the hour whether or not it is doing anything.** At
  the time of the recorded runs (September 2026, RunPod) the PRO 6000 was
  about $1.99/hr and the A6000 about $0.53/hr; prices move, check before
  planning around them.
- **Nothing on the pod needs saving.** All ragline state is local, so a pod
  can be terminated the moment no ingest batch or chat is mid-flight. An
  ingest interrupted by a teardown resumes: finished documents are skipped by
  hash on the next run, the rest are reprocessed.
- **Parsing is local and CPU-bound**, and for a large ingest it, not the GPU,
  sets the wall-clock time. `BATCH_MAX_PARALLEL` (default 3) is how many
  documents are in flight; raise it towards your core count.
- **After a restart, the first query is slow**: the BM25 index is rebuilt in
  memory from the stored chunks.
