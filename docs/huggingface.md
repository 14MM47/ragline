# Model weights from Hugging Face

Everything a pod touches on the Hugging Face side: which repos to pull, the
token + gated-model access, fast downloads, **caching to a persistent volume so pods
don't re-download on every boot**, how vLLM and TEI consume the hub, and the
offline path. Companion to [gpu-pod.md](gpu-pod.md).

None of this is ragline configuration — it belongs to the pod's environment.
[podlink](https://github.com/14MM47/podlink) automates most of it; this page is
for building or debugging a pod by hand.

> **Model repos move.** The ids below existed and were pulled in mid-2026. Confirm
> the exact repo path, and that the quantised build you want exists, before pinning.

---

## 1. What gets pulled from HF (and how big)

All model weights for the three pod services come from the HF Hub. vLLM and TEI
download by **repo id** at first launch. Two example profiles for a 96 GB card —
`--quantization` is per-model: `awq` for the Qwen/GLM AWQ builds, `mxfp4` for gpt-oss.

| Role | Repo (balanced profile) | ~Download | Gated? |
|------|-------------------------|-----------|--------|
| **LLM** (vLLM, `--quantization awq`) | `stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ` (Apache-2.0) | ~18 GB @4-bit | no |
| **Embedder** (TEI) | `Qwen/Qwen3-Embedding-8B` (Apache-2.0) | ~16 GB | no |
| **Reranker** (TEI) | `BAAI/bge-reranker-v2-m3` | ~2.3 GB | no |

| Role | Repo (max-reasoning profile) | ~Download | Gated? |
|------|------------------------------|-----------|--------|
| **LLM** (vLLM, `--quantization mxfp4`) | `openai/gpt-oss-120b` (Apache-2.0, native MXFP4) | ~63 GB | no |
| **Embedder** (TEI) | `BAAI/bge-m3` (light — pairs with the 120B) | ~2.3 GB | no |
| **Reranker** (TEI) | `BAAI/bge-reranker-v2-m3` | ~2.3 GB | no |

Fallback LLMs: balanced → `QuixiAI/Qwen3-30B-A3B-AWQ`; max → `cyankiwi/GLM-4.5-Air-AWQ-4bit`
(MIT, ~59 GB) or `twhitworth/gpt-oss-120b-awq-w4a16` (AWQ, ~33 GB). **Do not** use
`Qwen/Qwen3-Reranker-*` on TEI — TEI can't serve decoder rerankers; serve those on vLLM
(`RERANKER_API_FORMAT=cohere` in ragline) and keep bge-reranker for TEI.

**Disk sizing:** provision the cache volume for the **sum** of the profile you pick,
plus ~20% headroom. Balanced (30B+Qwen-embed) ≈ 40 GB; max-reasoning (120B+bge) ≈ 80 GB.
All these repos are **ungated** — the token is only needed for rate limits.

---

## 2. HF token — one read token, set once

1. Create a **read** token at `https://huggingface.co/settings/tokens` (fine-grained
   read is fine; it must have "read access to public gated repos you can access").
2. Expose it to every process that pulls from the hub via env-var. Both names are
   honoured; set `HF_TOKEN` (newer) — some tools still read `HUGGING_FACE_HUB_TOKEN`:

   ```bash
   export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx
   export HUGGING_FACE_HUB_TOKEN=$HF_TOKEN   # belt-and-braces for older TEI/vLLM
   ```

3. **Gated models** (many large LLMs — GLM, some Llama/Qwen variants) require clicking
   *"Agree and access repository"** on the model page **with the same HF account** that
   owns the token, once. Ungated repos (bge-*, Qwen3-Embedding/Reranker) need only the
   token for rate limits. If a pull 401/403s, the model is gated and the account hasn't
   accepted terms.

> **Secrets handling:** the HF token is a credential — inject it via the pod's
> secret/env mechanism, never bake it into an image layer or commit it.

---

## 3. Fast downloads — hf_transfer

Large LLM pulls are much faster with the Rust accelerated downloader:

```bash
pip install "huggingface_hub[hf_transfer]" hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1
```

Both vLLM and TEI respect this when the package is present. On a fresh pod this can cut
a 55 GB LLM pull from ~30 min to a few minutes on a fast link.

---

## 4. The cache volume — the single most important decision

**By default every model re-downloads on every fresh pod.** To avoid paying that
download (time + bandwidth) on each "pod up", point the HF cache at a **persistent /
network volume** that survives teardown.

- HF cache root is controlled by **`HF_HOME`** (default `~/.cache/huggingface`).
- On RunPod, mount a network volume at `/workspace` (persists across pods) and set:

  ```bash
  export HF_HOME=/workspace/hf-cache
  ```

- **TEI** caches to `/data` **inside the container** — mount the same host volume there:

  ```bash
  -v /workspace/hf-cache:/data
  ```

- **vLLM** uses `HF_HOME` directly — pass it into the process/container.

**The flow:** first pod-up downloads into `/workspace/hf-cache` (slow, once);
every subsequent pod-up finds the weights already present and starts serving in the
time it takes to load them into VRAM (seconds–low minutes), not re-download. Treat the
cache volume as build infrastructure, not per-pod scratch.

---

## 5. Pre-warming the cache (optional but recommended)

Rather than let the first *serving* launch block on a cold download, pre-pull into the
volume with the CLI so failures surface early and readiness is fast:

```bash
# newer CLI is `hf`; older installs expose `huggingface-cli` (same subcommands)
hf auth login --token "$HF_TOKEN"            # or: huggingface-cli login

# max-reasoning profile (swap the LLM line for the balanced profile):
hf download openai/gpt-oss-120b
hf download BAAI/bge-m3
hf download BAAI/bge-reranker-v2-m3
# balanced LLM instead: hf download stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ
#                       hf download Qwen/Qwen3-Embedding-8B
```

`hf download <repo>` populates `$HF_HOME`; vLLM/TEI then load from cache with no network
call. Run this as a one-off "prime the volume" job, separate from the serving pod.

---

## 6. How each service consumes the hub

### vLLM (LLM, :8000)
`vllm serve <HF_REPO_ID>` resolves the repo from the hub, honouring `HF_HOME`,
`HF_TOKEN`, and `HF_HUB_ENABLE_HF_TRANSFER`. **The quant is baked into the repo and the
flag must match it:** an `...-AWQ` repo needs `--quantization awq`; `gpt-oss-120b` ships
native MXFP4 and needs `--quantization mxfp4` (+ vLLM ≥0.10.1-gptoss). vLLM does not
quantise on the fly — a full-precision repo with `--quantization awq` errors.

### TEI (embedder :8080, reranker :8081)
`--model-id <HF_REPO_ID>` downloads from the hub into `/data`. Pass the token and cache
volume into the container:

```bash
docker run --gpus all -p 8080:80 \
  -e HF_TOKEN=$HF_TOKEN -e HUGGING_FACE_HUB_TOKEN=$HF_TOKEN \
  -e HF_HUB_ENABLE_HF_TRANSFER=1 \
  -v /workspace/hf-cache:/data \
  ghcr.io/huggingface/text-embeddings-inference:latest \
  --model-id BAAI/bge-m3
```

The TEI *container image* itself comes from **GHCR** (`ghcr.io/huggingface/...`), not
HF — only the model weights come from the HF Hub. Pin a version tag rather than
`:latest` for reproducible pods once a working combo is found.

---

## 7. Air-gap / offline mode

For a network-restricted deployment: pre-populate the cache volume once
(from a connected host or the prime job in §5), then force fully offline operation so no
process attempts a hub call:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

With these set, vLLM and TEI serve purely from `$HF_HOME` / `/data`. Any missing file
becomes a hard error instead of a silent download — which is the desired behaviour in an
air-gapped build (fail loud, don't phone home).

---

## 8. Checklist

**Pod-up (first time / cold volume):**
1. Ensure `HF_TOKEN` is injected (secret), and gated LLM terms accepted on the account.
2. Mount the persistent cache volume; set `HF_HOME` (vLLM) and `-v …:/data` (TEI).
3. `HF_HUB_ENABLE_HF_TRANSFER=1` for fast first pull.
4. (Recommended) run the §5 prime job before starting serving, so readiness isn't
   gated on a multi-GB cold download.

**Pod-up (warm volume — the normal case):**
- Cache present → services load from disk to VRAM; no HF calls. Fast readiness.

**Pin for reproducibility:**
- Pin the **TEI image tag** (not `:latest`) and the **exact model repo revisions** once
  a working set is validated, so a re-pod can't silently pull a changed model.

**Sizing:**
- Cache volume ≥ sum of chosen profile's downloads + ~20% (§1).

---

## 9. Env-var quick reference (HF side)

| Var | Purpose | Value |
|-----|---------|-------|
| `HF_TOKEN` | auth for pulls / gated repos | `hf_…` (secret) |
| `HUGGING_FACE_HUB_TOKEN` | legacy alias some tools read | = `HF_TOKEN` |
| `HF_HOME` | cache root (vLLM & CLI) | `/workspace/hf-cache` |
| `HF_HUB_ENABLE_HF_TRANSFER` | fast Rust downloader | `1` |
| `HF_HUB_OFFLINE` | forbid hub calls (air-gap) | `1` when offline |
| `TRANSFORMERS_OFFLINE` | same, transformers layer | `1` when offline |
| TEI `-v host:/data` | TEI's in-container cache | mount the same volume |

> None of these touch ragline's own config — they belong to the **pod** environment
> (vLLM process / TEI containers), not ragline's `.env`. ragline only ever sees the
> three HTTP endpoints ([gpu-pod.md](gpu-pod.md)).
