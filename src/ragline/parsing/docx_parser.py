"""DocxParser — Word documents split into heading-delimited sections.

Ported from raggles. DOCX has no reliable page notion (pagination happens at
render time), so each Heading-style paragraph starts a new "section" that
plays the role of a page: PageContent.page_number is really a 1-based section
number, and citations for DOCX files reference sections, not print pages.
"""

from pathlib import Path

import docx
import structlog

from ragline.parsing.base import BaseParser
from ragline.parsing.models import PageContent, ParsedDocument

log = structlog.get_logger()


class DocxParser(BaseParser):
    def parse(self, file_path: Path) -> ParsedDocument:
        log.info("parsing docx", file=file_path.name)
        # python-docx object model: paragraphs + tables.
        document = docx.Document(str(file_path))

        sections: list[PageContent] = []
        current_headers: list[str] = []
        current_text = ""
        current_section = 1

        for para in document.paragraphs:
            text = para.text.strip()
            # Skip blank paragraphs entirely.
            if not text:
                continue

            # Word heading styles are named "Heading 1", "Heading 2", ...
            is_heading = para.style and para.style.name and para.style.name.startswith("Heading")

            if is_heading:
                # A new heading closes the previous section (if non-empty).
                if current_text.strip():
                    sections.append(
                        PageContent(
                            page_number=current_section,
                            text=current_text.strip(),
                            headers=list(current_headers),
                        )
                    )
                    current_section += 1
                    current_text = ""
                # Start the new section, headed by this heading text.
                current_headers = [text]
                current_text = text + "\n"
            else:
                # Body paragraph — append to the running section.
                current_text += text + "\n"

        # Flush the final section after the loop.
        if current_text.strip():
            sections.append(
                PageContent(
                    page_number=current_section,
                    text=current_text.strip(),
                    headers=list(current_headers),
                )
            )

        # Tables are collected separately by python-docx; render each as
        # markdown-style rows and attach to the last section.
        for table in document.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                table_text = "\n".join(rows)
                if sections:
                    sections[-1].tables.append(table_text)
                else:
                    # Document consisting solely of a table.
                    sections.append(
                        PageContent(page_number=1, text=table_text, tables=[table_text])
                    )

        if not sections:
            # Fallback for documents with no headings and no tables:
            # everything becomes one section.
            all_text = "\n".join(p.text for p in document.paragraphs if p.text.strip())
            sections = [PageContent(page_number=1, text=all_text or "(empty document)")]

        return ParsedDocument(filename=file_path.name, file_type="docx", pages=sections)
