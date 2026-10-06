"""scripts/evaluate.py — endpoint hosts recorded in a results file.

Results files are published (eval/results/), so the host recorded for each
endpoint must not name the RunPod pod it ran on. Loads the script as a module;
only the pure helper is exercised — no pipeline, no endpoints.
"""

import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import structlog

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate.py"
spec = importlib.util.spec_from_file_location("evaluate_script", SCRIPT)
evaluate_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate_script)


def test_runpod_proxy_host_has_its_pod_id_masked():
    host = evaluate_script._host("https://abc123def456gh-8000.proxy.runpod.net/v1")
    assert host == "<pod-id>-8000.proxy.runpod.net"
    assert "abc123def456gh" not in host


def test_other_hosts_are_recorded_as_they_are():
    # Cloud APIs and self-hosted servers carry no pod id; keep them readable.
    assert evaluate_script._host("https://api.openai.com/v1") == "api.openai.com"
    assert evaluate_script._host("http://gpu-box:8000/v1") == "gpu-box:8000"
    # An unset endpoint (e.g. no API reranker) is an empty string, not an error.
    assert evaluate_script._host("") == ""


def test_hosts_exclude_url_credentials_and_preserve_ports():
    assert evaluate_script._host("https://user:private-password@abc123-8000.proxy.runpod.net:443/v1") == (
        "<pod-id>-8000.proxy.runpod.net:443"
    )
    assert evaluate_script._host("http://user:private-password@[::1]:8000/v1") == "[::1]:8000"


async def test_evaluation_redacts_startup_logs_http_errors_and_saved_results(tmp_path, monkeypatch, capsys, caplog):
    from ragline.api import dependencies
    from ragline.config import settings
    from ragline.retrieval.pipeline import RetrievalPipeline
    from ragline.storage import metadata_db

    pod_id = "syntheticpod123"
    url = f"https://{pod_id}-8081.proxy.runpod.net/v1/rerank"
    golden = tmp_path / "private-home" / "golden.json"
    golden.parent.mkdir()
    golden.write_text(json.dumps([{
        "id": "A01", "question": "What is the rating?", "expected_sources": ["manual.pdf"],
    }]))
    output = tmp_path / "results.json"
    response = httpx.Response(503, request=httpx.Request("POST", url))
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        error = exc
    agent = SimpleNamespace(query=AsyncMock(side_effect=error))

    monkeypatch.setattr(settings, "reranker_provider", "api")
    monkeypatch.setattr(settings, "reranker_base_url", url.removesuffix("/v1/rerank"))
    monkeypatch.setattr(settings, "reranker_api_key", "")
    monkeypatch.setattr(settings, "reranker_api_format", "tei")
    monkeypatch.setattr(metadata_db, "init_db", AsyncMock())
    monkeypatch.setattr(dependencies, "get_rag_agent", lambda: agent)

    # Construct the real pipeline in the evaluator's startup path: this was
    # where the full reranker URL escaped before masking was configured.
    def get_pipeline():
        pipeline = RetrievalPipeline(SimpleNamespace(), SimpleNamespace())

        async def rebuild():
            logging.getLogger("httpx").warning("HTTP request failed: %s", url)

        pipeline.rebuild_bm25_index = rebuild
        return pipeline

    monkeypatch.setattr(dependencies, "get_retrieval_pipeline", get_pipeline)
    monkeypatch.setattr(sys, "argv", ["evaluate.py", str(golden), "-o", str(output)])
    old_config = structlog.get_config().copy()
    old_formatters = [(handler, handler.formatter) for handler in logging.getLogger().handlers]
    try:
        assert await evaluate_script.main() == 0
        stdout, stderr = capsys.readouterr()
        logs = stdout + stderr + caplog.text
        assert "using api reranker" in logs
        assert "HTTP request failed" in logs
        assert pod_id not in logs
        assert str(golden.parent) not in logs
        result = json.loads(output.read_text())
        assert pod_id not in output.read_text()
        assert result["run"]["golden_set"] == "golden.json"
        assert result["per_question"][0]["source_hit"] is False
        assert "503" in result["per_question"][0]["error"]
        assert "<pod-id>-8081.proxy.runpod.net" in result["per_question"][0]["error"]
    finally:
        structlog.configure(**old_config)
        for handler, formatter in old_formatters:
            handler.setFormatter(formatter)
