# Third-party licences

ragline's own code is released under the [MIT licence](LICENSE). It is built
on other people's work, some of it under different terms. This page lists what
is worth knowing before you redistribute or host it. It is a summary, not
legal advice; each project's own licence text is authoritative.

## Python dependencies that are not permissively licensed

The PDF parser is the Artifex PyMuPDF family. The licences below are the ones
each package declares in its own metadata at the pinned version (1.28.2).

| Package | Declared licence | Where it is used |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) (`pymupdf`) | AGPL-3.0, or a commercial licence from Artifex | PDF parsing, layout analysis, page counting |
| [pymupdf4llm](https://pypi.org/project/pymupdf4llm/) | AGPL-3.0, or a commercial licence from Artifex | PDF to per-page Markdown |
| [pymupdf-layout](https://pypi.org/project/pymupdf-layout/) | AGPL-3.0, or a commercial licence from Artifex | Not imported by ragline; a hard requirement of `pymupdf4llm`, which uses it as its layout engine |

All three are installed by `uv sync`, and ragline does not parse PDFs without
them.

**The version matters.** Up to 1.28.0, `pymupdf-layout` was licensed
PolyForm Noncommercial, which ruled out commercial use of anything that
installed it. Artifex
[moved it to the AGPL from 1.28.2](https://pymupdf.io/blog/open-source-all-the-way-down-pymupdf4llm-goes-fully-agpl),
which is what ragline pins. Do not downgrade the pin below 1.28.2 without
re-reading the licence of what you would be installing. (The 1.28.2 wheel
still carries a generic "Other/Proprietary" trove classifier; its licence
field and bundled `COPYING` file say AGPL.)

What that means in practice:

- **Using ragline yourself** — on your own machine, for research, evaluation
  or work — is permitted by the AGPL.
- **Distributing ragline bundled with PyMuPDF** (a container image, an
  installer), or **letting other people use an instance over a network**,
  brings the AGPL's source-availability terms into play for the combined
  work. ragline's MIT licence is compatible with that — MIT code can be
  combined into an AGPL work — but the MIT licence alone does not describe
  your obligations in those cases.
- If the AGPL does not fit, Artifex sells commercial licences, or the PDF
  parser can be replaced.

ragline's MIT licence covers ragline's own source code only; it cannot and
does not relicense these packages.

No other installed dependency declares a copyleft or noncommercial licence at
the locked versions (checked against package metadata; `uv.lock` pins the
exact set). On Linux, PyTorch pulls in NVIDIA's CUDA runtime libraries, which
are proprietary but freely redistributable under NVIDIA's terms; they are only
used by the optional local reranker.

## Other tools

- **Qdrant** (Apache-2.0) runs as a separate container; ragline talks to it
  over HTTP.
- **Tesseract** (Apache-2.0) is optional and invoked as an external binary.
- **Frontend**: React, Vite, Tailwind CSS and Vitest are MIT-licensed.

## Model weights

ragline ships no model weights. It calls whatever models you serve, and their
licences are yours to check. For reference, the ones named in this
repository's documentation and recorded runs:

| Model | Licence as published by its authors |
|---|---|
| `Qwen/Qwen3-Embedding-8B`, `Qwen/Qwen3-Reranker-0.6B` | Apache-2.0 |
| `stelterlab/Qwen3-30B-A3B-Instruct-2507-AWQ` (a quantisation of Qwen3-30B-A3B) | Apache-2.0 |
| `openai/gpt-oss-120b` | Apache-2.0 |
| `BAAI/bge-reranker-v2-m3`, `BAAI/bge-m3` | Apache-2.0 / MIT — see each model card |
| `RedHatAI/Qwen3.8-27B-INT4` | see its model card |

With `RERANKER_PROVIDER=local`, ragline downloads `BAAI/bge-reranker-v2-m3`
from Hugging Face on first start.

## Documents

The evaluation corpus is not distributed with ragline. The datasheets and
manuals indexed in [eval/corpus/](eval/corpus/README.md) are the copyright of
their respective vendors; the index records only their names, sizes, digests
and public download addresses. The golden question set and the recorded runs
quote short passages from them as evidence for the answers being evaluated.
Product and company names are trademarks of their owners and are used only to
identify the documents.
