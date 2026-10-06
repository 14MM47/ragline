"""MemoryStore — one JSON file per chat session under settings.memory_dir.

Ported from raggles (which used data/sessions; ragline makes the directory
configurable). Writes are atomic (tmp file + os.replace) so a crash mid-save
never corrupts a session.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog

from ragline.chat.models import SessionMemory
from ragline.config import settings

log = structlog.get_logger()


class MemoryStore:
    def __init__(self, sessions_dir: Path | None = None):
        # Configurable location, created eagerly.
        self._dir = sessions_dir or Path(settings.memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        """Resolve a session id to its file, neutralizing path tricks.

        session_id arrives from the URL path; strip anything that could
        escape the sessions directory (e.g. "../../x").
        """
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", Path(session_id).name)
        if not safe_id or set(safe_id) <= {"."}:
            safe_id = "_invalid"
        return self._dir / f"{safe_id}.json"

    def load(self, session_id: str) -> SessionMemory:
        """Load a session, or return a fresh empty one."""
        path = self._path(session_id)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return SessionMemory(**data)
            except Exception as e:
                # A corrupt/unreadable session file must NOT brick the
                # conversation (mirrors list_sessions, which skips corrupt
                # files). Degrade to a fresh session instead of 500-ing every
                # future message and history load for this id.
                log.warning("corrupt session file, starting fresh", session_id=session_id, error=str(e))
        # Unknown or corrupt session id -> new session starting now.
        return SessionMemory(
            session_id=session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def save(self, memory: SessionMemory) -> None:
        """Atomically persist a session (write tmp, then rename over)."""
        path = self._path(memory.session_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(memory.model_dump_json(indent=2))
        os.replace(tmp, path)
        log.debug("session saved", session_id=memory.session_id, turns=memory.turn_count)

    def list_sessions(self) -> list[dict]:
        """Summaries of all sessions, newest-modified first.

        total_tokens sums each turn's whole-turn prompt+completion — the
        header's session token counter reads this.
        """
        sessions = []
        for path in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text())
                turns = data.get("turns", [])
                total_tokens = sum(
                    (t.get("prompt_tokens") or 0) + (t.get("completion_tokens") or 0)
                    for t in turns
                    if isinstance(t, dict)
                )
                sessions.append({
                    "session_id": data["session_id"],
                    "created_at": data["created_at"],
                    "turn_count": len(turns),
                    "total_tokens": total_tokens,
                    "summary": data.get("summary", ""),
                    "topics": data.get("topics", []),
                })
            except Exception:
                # A corrupt file is skipped, never fatal to the listing.
                log.warning("corrupt session file", path=str(path))
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session file; True when something was removed."""
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False
