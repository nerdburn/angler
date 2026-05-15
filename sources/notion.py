import os
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

                # Extract rich_text from common block types
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
                    # Don't recurse into child pages — they'll be indexed separately
                    continue

                if line.strip():
                    text_parts.append(line)

                # Recurse into blocks that have children
                if block.get("has_children") and block_type not in ("child_page", "child_database"):
                    child_text = self._blocks_to_text(block["id"])
                    if child_text.strip():
                        text_parts.append(child_text)

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return "\n".join(text_parts)

    def _get_page_title(self, page: dict) -> str:
        """Extract title from a Notion page object."""
        props = page.get("properties", {})
        for prop in props.values():
            if prop["type"] == "title":
                return "".join(
                    rt.get("plain_text", "") for rt in prop.get("title", [])
                )
        return "Untitled"

    def _get_page_url(self, page: dict) -> str:
        return page.get("url", "")

    def _fetch_from_search(self) -> list[Document]:
        """Fetch all pages the integration has access to."""
        documents = []
        cursor = None

        while True:
            response = self.client.search(
                filter={"property": "object", "value": "page"},
                start_cursor=cursor,
                page_size=100,
            )

            for page in response["results"]:
                doc = self._page_to_document(page)
                if doc:
                    documents.append(doc)

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return documents

    def _fetch_from_databases(self) -> list[Document]:
        """Fetch all pages from specific databases."""
        documents = []

        for db_id in self.database_ids:
            cursor = None
            while True:
                response = self.client.databases.query(
                    database_id=db_id,
                    start_cursor=cursor,
                    page_size=100,
                )

                for page in response["results"]:
                    doc = self._page_to_document(page)
                    if doc:
                        documents.append(doc)

                if not response.get("has_more"):
                    break
                cursor = response.get("next_cursor")

        return documents

    def _page_to_document(self, page: dict) -> Document | None:
        """Convert a Notion page to a Document."""
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

    def fetch_documents(self) -> list[Document]:
        if self.database_ids:
            return self._fetch_from_databases()
        return self._fetch_from_search()
