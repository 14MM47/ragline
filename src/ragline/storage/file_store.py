"""File store — managed copies of every uploaded document.

Ported from raggles, local-only (the Azure blob variant is not carried over;
the base class remains so an object-store backend can be added when scaling
toward the 12TB corpus). Files live under settings.upload_dir as
"{batch_id}/{relative_path}" and are served back by GET /documents/{id}/content
— the "Open copy" link in citations.
"""

from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from ragline.config import settings

log = structlog.get_logger()


class BaseFileStore(ABC):
    @abstractmethod
    async def save(self, filename: str, data: bytes) -> str:
        """Save file and return its storage path/URL."""
        ...

    @abstractmethod
    async def get_path(self, filename: str) -> Path:
        """Resolve a stored filename to a local filesystem path."""
        ...

    @abstractmethod
    async def delete(self, filename: str) -> None:
        """Remove a stored file (no-op when absent)."""
        ...

    @abstractmethod
    async def list_files(self) -> list[str]:
        """List stored top-level files."""
        ...


class LocalFileStore(BaseFileStore):
    def __init__(self, upload_dir: str | None = None):
        # Root directory for all managed copies; created eagerly.
        self._dir = Path(upload_dir or settings.upload_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, filename: str) -> Path:
        """Resolve a filename within the upload directory, rejecting traversal.

        Batch paths come from user-supplied ZIP entries, so "../" escapes must
        be blocked here — this is the single choke point for that.
        """
        path = (self._dir / filename).resolve()
        if not path.is_relative_to(self._dir.resolve()):
            raise ValueError(f"Path escapes upload directory: {filename}")
        return path

    async def save(self, filename: str, data: bytes) -> str:
        """Write bytes under the store, creating intermediate directories."""
        path = self._safe_path(filename)
        # Batch uploads use "{batch_id}/{rel_path}" — ensure parents exist.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        log.info("saved file", filename=filename, size=len(data))
        return str(path)

    async def get_path(self, filename: str) -> Path:
        """Path for reading a stored file (content serving)."""
        return self._safe_path(filename)

    async def delete(self, filename: str) -> None:
        """Delete a stored file and clean up an emptied batch directory."""
        path = self._safe_path(filename)
        if path.exists():
            path.unlink()
            # Remove the parent batch directory if it is now empty.
            if path.parent != self._dir and path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()
                log.info("removed empty batch dir", dir=str(path.parent.name))
            log.info("deleted file", filename=filename)

    async def list_files(self) -> list[str]:
        """Names of files directly under the store root."""
        return [f.name for f in self._dir.iterdir() if f.is_file()]


def create_file_store() -> BaseFileStore:
    """Factory — local only in v1 (object-store backend is a roadmap item)."""
    return LocalFileStore()
