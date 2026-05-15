from dataclasses import dataclass, field


@dataclass
class Document:
    id: str
    content: str
    metadata: dict = field(default_factory=dict)


class Source:
    """Base class for content sources."""

    def __init__(self, config: dict):
        self.config = config

    def fetch_documents(self) -> list[Document]:
        raise NotImplementedError
