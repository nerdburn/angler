import os
from datetime import datetime, timezone
import dropbox
import pymupdf
from .base import Source, Document

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".rtf", ".pdf"}


class DropboxSource(Source):
    """Index text and PDF files from a Dropbox folder."""

    def __init__(self, config: dict):
        super().__init__(config)
        token = config.get("token", os.environ.get("DROPBOX_TOKEN", ""))
        if not token:
            raise ValueError("Dropbox source requires token or DROPBOX_TOKEN env var")

        self.dbx = dropbox.Dropbox(token)
        self.folder_path = config.get("folder_path", "")  # "" = root
        self.extensions = set(config.get("extensions", TEXT_EXTENSIONS))

    def _list_files(self, path: str, since: datetime | None = None) -> list[dropbox.files.FileMetadata]:
        """Recursively list all files in a Dropbox folder."""
        files = []

        result = self.dbx.files_list_folder(path, recursive=True)
        files.extend(self._collect_files(result, since))

        while result.has_more:
            result = self.dbx.files_list_folder_continue(result.cursor)
            files.extend(self._collect_files(result, since))

        return files

    def _collect_files(self, result, since: datetime | None = None) -> list[dropbox.files.FileMetadata]:
        """Filter list results to only indexable files."""
        files = []
        for entry in result.entries:
            if not isinstance(entry, dropbox.files.FileMetadata):
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in self.extensions:
                continue
            if since:
                modified = entry.server_modified.replace(tzinfo=timezone.utc)
                if modified <= since:
                    continue
            files.append(entry)
        return files

    def _download_bytes(self, path: str) -> bytes:
        _, response = self.dbx.files_download(path)
        return response.content

    def _extract_text(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        raw = self._download_bytes(path)

        if ext == ".pdf":
            return self._extract_pdf_text(raw)

        return raw.decode("utf-8", errors="replace")

    def _extract_pdf_text(self, data: bytes) -> str:
        doc = pymupdf.open(stream=data, filetype="pdf")
        pages = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(text)
        doc.close()
        return "\n\n".join(pages)

    def fetch_documents(self, since: datetime | None = None) -> list[Document]:
        files = self._list_files(self.folder_path, since)
        documents = []

        for file in files:
            try:
                content = self._extract_text(file.path_display)
            except Exception:
                continue

            if not content.strip():
                continue

            documents.append(Document(
                id=f"dropbox://{file.id}",
                content=content,
                metadata={
                    "source": "dropbox",
                    "title": file.name,
                    "path": file.path_display,
                    "last_modified": file.server_modified.isoformat(),
                },
            ))

        return documents
