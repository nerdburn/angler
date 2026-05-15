import os
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from .base import Source, Document

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]


class GoogleDocsSource(Source):
    """Index documents from a Google Drive folder."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.folder_id = config.get("folder_id", "")
        if not self.folder_id:
            raise ValueError("Google Docs source requires folder_id")

        creds = self._get_credentials(config)
        self.drive = build("drive", "v3", credentials=creds)
        self.docs = build("docs", "v1", credentials=creds)

    def _get_credentials(self, config: dict):
        creds_file = config.get("credentials_file", os.environ.get("GOOGLE_CREDENTIALS_FILE", ""))
        creds_json = config.get("credentials_json", os.environ.get("GOOGLE_CREDENTIALS_JSON", ""))

        if creds_file:
            return service_account.Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        elif creds_json:
            info = json.loads(creds_json)
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            raise ValueError(
                "Google Docs source requires credentials_file or GOOGLE_CREDENTIALS_JSON env var"
            )

    def _list_docs(self, folder_id: str, since: datetime | None = None) -> list[dict]:
        """Recursively list Google Docs in a folder, optionally filtered by modified time."""
        docs = []
        page_token = None

        q = f"'{folder_id}' in parents and trashed = false"
        if since:
            q += f" and modifiedTime > '{since.isoformat()}'"

        while True:
            response = self.drive.files().list(
                q=q,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink)",
                pageSize=100,
                pageToken=page_token,
            ).execute()

            for file in response.get("files", []):
                if file["mimeType"] == "application/vnd.google-apps.document":
                    docs.append(file)
                elif file["mimeType"] == "application/vnd.google-apps.folder":
                    docs.extend(self._list_docs(file["id"], since))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return docs

    def _get_doc_text(self, doc_id: str) -> str:
        content = self.drive.files().export(
            fileId=doc_id,
            mimeType="text/plain",
        ).execute()

        if isinstance(content, bytes):
            return content.decode("utf-8")
        return str(content)

    def fetch_documents(self, since: datetime | None = None) -> list[Document]:
        docs = self._list_docs(self.folder_id, since)
        documents = []

        for doc in docs:
            content = self._get_doc_text(doc["id"])
            if not content.strip():
                continue

            documents.append(Document(
                id=f"gdocs://{doc['id']}",
                content=content,
                metadata={
                    "source": "google_docs",
                    "title": doc["name"],
                    "url": doc.get("webViewLink", ""),
                    "last_modified": doc.get("modifiedTime", ""),
                },
            ))

        return documents
