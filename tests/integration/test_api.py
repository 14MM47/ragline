"""Integration round-trip: upload -> poll batch -> query -> chat.

Skipped unless RAGLINE_INTEGRATION=1 because it runs against the REAL local
stack: the configured .env, a running Qdrant, and (for the query/chat legs)
a reachable LLM/embedding endpoint. Run before merging pipeline changes:

    RAGLINE_INTEGRATION=1 .venv/bin/python -m pytest tests/integration -q
"""

import io
import os
import time
import zipfile

import pytest

# Only run when explicitly requested — this touches real services and ./data.
pytestmark = pytest.mark.skipif(
    os.environ.get("RAGLINE_INTEGRATION") != "1",
    reason="integration test: set RAGLINE_INTEGRATION=1 with Qdrant + endpoint configured",
)


@pytest.fixture(scope="module")
def client():
    """Sync TestClient over the real app (runs the startup lifespan)."""
    from fastapi.testclient import TestClient

    from ragline.main import app

    with TestClient(app) as c:
        yield c


def _tiny_pdf_bytes(text: str) -> bytes:
    """Build a minimal one-page PDF containing `text` using pymupdf."""
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    # Insert enough text that the OCR fallback never triggers.
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_zip_upload_with_original_base_path_round_trip(client):
    """ZIP batch upload records original paths and processes to completion."""
    # Two tiny PDFs inside a folder structure, zipped in memory.
    pdf = _tiny_pdf_bytes(
        "The QX-9 controller supports Modbus TCP. "
        "Its maximum operating temperature is 60 degrees Celsius. " * 5
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plc/qx9_manual.pdf", pdf)
    buf.seek(0)

    # Upload with an original base path (the provenance feature under test).
    resp = client.post(
        "/api/batches/upload",
        files={"zip_file": ("docs.zip", buf.read(), "application/zip")},
        data={"original_base_path": "\\\\server\\eng\\ProjectX"},
    )
    assert resp.status_code == 200, resp.text
    batch_id = resp.json()["batch_id"]

    # Poll the batch until processing finishes (embedding + KG need the
    # configured endpoint; allow a generous window).
    deadline = time.time() + 300
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/batches/{batch_id}").json()
        if status["status"] in ("completed", "completed_with_errors"):
            break
        time.sleep(2)

    assert status is not None and status["status"] == "completed", status
    # The document carries the joined UNC original path.
    doc = status["documents"][0]
    assert doc["original_path"] == "\\\\server\\eng\\ProjectX\\plc\\qx9_manual.pdf"
    assert doc["status"] == "ready"

    # Content endpoint serves the managed copy.
    content = client.get(f"/api/documents/{doc['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("application/pdf")

    # One-shot query cites the document and returns the original path.
    q = client.post("/api/query", json={"question": "What protocol does the QX-9 controller support?"})
    assert q.status_code == 200, q.text
    body = q.json()
    assert body["sources"], body["answer"]
    assert any(s["source_file"] == "qx9_manual.pdf" for s in body["sources"])
    assert any(s["original_path"].startswith("\\\\server\\eng\\ProjectX") for s in body["sources"])
    assert body["prompt_tokens"] > 0

    # Chat SSE round-trip: answer frame then complete frame with tokens.
    chat_request = {
        "session_id": "it-session",
        "question": "What is the QX-9's max operating temperature?",
        "use_memory": True,
    }
    with client.stream("POST", "/api/chat", json=chat_request) as stream:
        events = stream.read().decode()
    assert "event: answer" in events
    assert "event: complete" in events
    assert "total_tokens" in events
