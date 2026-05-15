import os
import dropbox
from .base import Source, Document

# File extensions we can extract text from
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".rtf"}

# Dropbox export formats for Office docs
EXPORT_FORMATS = {
    "paper": "markdown",
}


class DropboxSource(Source):
    """Index text files from a Dropbox folder."""

    def __init__(self, config: dict):
        super().__init__(config)
        token = config.get("token", os.environ.get("DROPBOX_TOKEN", ""))
        if not token:
            raise ValueError("Dropbox source requires token or DROPBOX_TOKEN env var")

        self.dbx = dropbox.Dropbox(token)
        self.folder_path = config.get("folder_path", "")  # "" = root
        self.extensions = set(config.get("extensions", TEXT_EXTENSIONS))

    def _list_files(self, path: str) -> list[dropbox.files.FileMetadata]:
        """Recursively list all files in a Dropbox folder."""
        files = []

        result = self.dbx.files_list_folder(path, recursive=True)
        files.extend(self._collect_files(result))

        while result.has_more:
            result = self.dbx.files_list_folder_continue(result.cursor)
            files.extend(self._collect_files(result))

        return files

    def _collect_files(self, result) -> list[dropbox.files.FileMetadata]:
        """Filter list results to only indexable files."""
        files = []
        for entry in result.entries:
            if not isinstance(entry, dropbox.files.FileMetadata):
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in self.extensions:
                files.append(entry)
        return files

    def _download_text(self, path: str) -> str:
        """Download a file's content as text."""
        _, response = self.dbx.files_download(path)
        return response.content.decode("utf-8", errors="replace")

    def fetch_documents(self) -> list[Document]:
        files = self._list_files(self.folder_path)
        documents = []

        for file in files:
            try:
                content = self._download_text(file.path_display)
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
