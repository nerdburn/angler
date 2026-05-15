from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Document:
    id: str
    content: str
    metadata: dict = field(default_factory=dict)


class Source:
    """Base class for content sources."""

    def __init__(self, config: dict):
        self.config = config

    def fetch_documents(self, since: datetime | None = None) -> list[Document]:
        """Fetch documents. If `since` is provided, only return docs modified after that time."""
        raise NotImplementedError
