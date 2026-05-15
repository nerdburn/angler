import os
from datetime import datetime
from notion_client import Client
from .base import Source, Document


class NotionSource(Source):
    """Index pages from Notion."""

    def __init__(self, config: dict):
        super().__init__(config)
        token = config.get("token", os.environ.get("NOTION_TOKEN", ""))
        if not token:
            raise ValueError("Notion source requires token or NOTION_TOKEN env var")
        self.client = Client(auth=token)
        self.database_ids = config.get("databases", [])

    def _blocks_to_text(self, block_id: str) -> str:
        """Recursively extract text from Notion blocks."""
        text_parts = []
        cursor = None

        while True:
            response = self.client.blocks.children.list(
                block_id=block_id,
                start_cursor=cursor,
                page_size=100,
            )

            for block in response["results"]:
                block_type = block["type"]
                block_data = block.get(block_type, {})

                rich_text = block_data.get("rich_text", [])
                line = "".join(rt.get("plain_text", "") for rt in rich_text)

                if block_type in ("heading_1", "heading_2", "heading_3"):
                    line = f"\n{'#' * int(block_type[-1])} {line}\n"
                elif block_type == "bulleted_list_item":
                    line = f"- {line}"
                elif block_type == "numbered_list_item":
                    line = f"• {line}"
                elif block_type == "to_do":
                    checked = "x" if block_data.get("checked") else " "
                    line = f"[{checked}] {line}"
                elif block_type == "code":
                    line = f"```\n{line}\n```"
                elif block_type == "divider":
                    line = "---"
                elif block_type in ("child_page", "child_database"):
                    continue

                if line.strip():
                    text_parts.append(line)

                if block.get("has_children") and block_type not in ("child_page", "child_database"):
                    child_text = self._blocks_to_text(block["id"])
                    if child_text.strip():
                        text_parts.append(child_text)

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return "\n".join(text_parts)

    def _get_page_title(self, page: dict) -> str:
        props = page.get("properties", {})
        for prop in props.values():
            if prop["type"] == "title":
                return "".join(
                    rt.get("plain_text", "") for rt in prop.get("title", [])
                )
        return "Untitled"

    def _get_page_url(self, page: dict) -> str:
        return page.get("url", "")

    def _is_modified_since(self, page: dict, since: datetime) -> bool:
        edited = page.get("last_edited_time", "")
        if not edited:
            return True
        edited_dt = datetime.fromisoformat(edited.replace("Z", "+00:00"))
        return edited_dt > since

    def _fetch_from_search(self, since: datetime | None = None) -> list[Document]:
        documents = []
        cursor = None

        kwargs = {
            "filter": {"property": "object", "value": "page"},
            "page_size": 100,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }

        while True:
            if cursor:
                kwargs["start_cursor"] = cursor

            response = self.client.search(**kwargs)

            for page in response["results"]:
                # With descending sort, once we hit a page older than `since`, we can stop
                if since and not self._is_modified_since(page, since):
                    return documents

                doc = self._page_to_document(page)
                if doc:
                    documents.append(doc)

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return documents

    def _fetch_from_databases(self, since: datetime | None = None) -> list[Document]:
        documents = []

        for db_id in self.database_ids:
            cursor = None
            kwargs = {"database_id": db_id, "page_size": 100}

            if since:
                kwargs["filter"] = {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"after": since.isoformat()},
                }

            while True:
                if cursor:
                    kwargs["start_cursor"] = cursor

                response = self.client.databases.query(**kwargs)

                for page in response["results"]:
                    doc = self._page_to_document(page)
                    if doc:
                        documents.append(doc)

                if not response.get("has_more"):
                    break
                cursor = response.get("next_cursor")

        return documents

    def _page_to_document(self, page: dict) -> Document | None:
        page_id = page["id"]
        title = self._get_page_title(page)
        content = self._blocks_to_text(page_id)

        if not content.strip():
            return None

        return Document(
            id=f"notion://{page_id}",
            content=content,
            metadata={
                "source": "notion",
                "title": title,
                "url": self._get_page_url(page),
                "last_edited": page.get("last_edited_time", ""),
            },
        )

    def fetch_documents(self, since: datetime | None = None) -> list[Document]:
        if self.database_ids:
            return self._fetch_from_databases(since)
        return self._fetch_from_search(since)
