from .base import Source, Document
from .git import GitSource
from .notion import NotionSource
from .google_docs import GoogleDocsSource
from .dropbox import DropboxSource

SOURCE_TYPES = {
    "git": GitSource,
    "notion": NotionSource,
    "google_docs": GoogleDocsSource,
    "dropbox": DropboxSource,
}
