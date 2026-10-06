"""scripts/apply_pod_env.py — the podlink client-env hook.

Loads the script as a module (it imports nothing from ragline) and checks the
block filter, the in-place merge, the atomic/mode-preserving write, and a full
run with restart disabled.
"""

import importlib.util
import os
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "apply_pod_env.py"
spec = importlib.util.spec_from_file_location("apply_pod_env", SCRIPT)
ape = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ape)

BLOCK = """\
LLM_BASE_URL=https://pod1-8000.proxy.example/v1
LLM_MODEL=ragline-llm
LLM_API_KEY=s3cret
EMBEDDING_BASE_URL=https://pod1-8080.proxy.example/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIMENSIONS=4096
EMBEDDING_API_KEY=s3cret
RERANKER_PROVIDER=api
RERANKER_BASE_URL=https://pod1-8081.proxy.example
RERANKER_API_KEY=s3cret
RERANKER_API_FORMAT=cohere
KG_EXTRACTION_CONCURRENCY=2
AUTH_ENABLED=false
"""


def test_parse_block_filters_to_pod_keys_and_defaults_format(capsys):
    found = ape.parse_block(BLOCK)
    assert "AUTH_ENABLED" not in found, "a block line must never reach auth settings"
    assert found["LLM_MODEL"] == "ragline-llm"
    assert found["KG_EXTRACTION_CONCURRENCY"] == "2"
    assert "AUTH_ENABLED" in capsys.readouterr().err
    # A TEI block omits RERANKER_API_FORMAT: absent means the tei default.
    tei = ape.parse_block(BLOCK.replace("RERANKER_API_FORMAT=cohere\n", ""))
    assert tei["RERANKER_API_FORMAT"] == "tei"


def test_parse_block_refuses_placeholders_and_non_blocks():
    with pytest.raises(SystemExit, match="placeholder"):
        ape.parse_block(BLOCK.replace("LLM_API_KEY=s3cret", "LLM_API_KEY=<your pod_bearer_token>"))
    with pytest.raises(SystemExit, match="LLM_BASE_URL"):
        ape.parse_block("FOO=bar\n")


def test_merge_replaces_in_place_and_appends_new_keys():
    env = (
        "# header comment\n"
        "AUTH_ENABLED=true\n"
        "LLM_BASE_URL=https://old-8000.proxy.example/v1\n"
        "KG_EXTRACTION_CONCURRENCY=20  # parallel LLM extraction calls\n"
        "QDRANT_COLLECTION=ragline\n"
    )
    out = ape.merge(env, {"LLM_BASE_URL": "https://new/v1", "KG_EXTRACTION_CONCURRENCY": "2",
                          "RERANKER_API_FORMAT": "cohere"})
    lines = out.splitlines()
    assert lines[0] == "# header comment"
    assert lines[1] == "AUTH_ENABLED=true", "untouched keys stay exactly where they were"
    assert lines[2] == "https://new/v1".join(["LLM_BASE_URL=", ""])
    assert lines[3] == "KG_EXTRACTION_CONCURRENCY=2"
    assert lines[4] == "QDRANT_COLLECTION=ragline"
    assert ape.MARKER in lines and lines[-1] == "RERANKER_API_FORMAT=cohere"
    # Idempotent: applying the same updates again changes nothing.
    assert ape.merge(out, {"LLM_BASE_URL": "https://new/v1", "KG_EXTRACTION_CONCURRENCY": "2",
                           "RERANKER_API_FORMAT": "cohere"}) == out


def test_write_env_backs_up_and_keeps_mode(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    env.chmod(0o600)
    ape.write_env(env, "A=2\n")
    assert env.read_text() == "A=2\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    bak = tmp_path / ".env.bak"
    assert bak.read_text() == "A=1\n" and stat.S_IMODE(bak.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env", ".env.bak"], "no temp files left"
    fresh = tmp_path / "new.env"
    ape.write_env(fresh, "B=1\n")
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600


def test_main_end_to_end_without_restart(tmp_path, monkeypatch, capsys):
    block = tmp_path / "ragline.env"
    block.write_text(BLOCK)
    env = tmp_path / ".env"
    env.write_text("AUTH_ENABLED=true\nLLM_BASE_URL=https://old/v1\nRERANKER_API_FORMAT=tei\n")
    monkeypatch.setenv("RAGLINE_ENV_FILE", str(env))
    monkeypatch.setenv("RAGLINE_APPLY_RESTART", "none")
    assert ape.main(["apply_pod_env.py", str(block)]) == 0
    text = env.read_text()
    assert "LLM_BASE_URL=https://pod1-8000.proxy.example/v1" in text
    assert "RERANKER_API_FORMAT=cohere" in text and "RERANKER_API_FORMAT=tei" not in text
    assert "AUTH_ENABLED=true" in text and "AUTH_ENABLED=false" not in text
    out = capsys.readouterr().out
    assert "s3cret" not in out, "the hook must never print a secret value"
    assert "restart: none" in out


def test_restart_rejects_unknown_mode(tmp_path):
    with pytest.raises(SystemExit, match="RAGLINE_APPLY_RESTART"):
        ape.restart("reboot", tmp_path)
    assert ape.restart("none", tmp_path) == "none"
    assert os.access(SCRIPT, os.X_OK), "podlink refuses a hook that is not executable"
