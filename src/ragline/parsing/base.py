"""BaseParser — the interface every file-format parser implements."""

from abc import ABC, abstractmethod
from pathlib import Path

from ragline.parsing.models import ParsedDocument


class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: Path) -> ParsedDocument:
        """Parse the file at `file_path` into the normalized document model.

        Runs synchronously (CPU-bound); the ingestion worker calls it inside
        a thread pool so the event loop is never blocked.
        """
        ...
