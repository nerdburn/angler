import os
import frontmatter
from pathlib import Path
from git import Repo
from .base import Source, Document


class GitSource(Source):
    """Index markdown files from a git repository."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.repo_url = config.get("repo_url", "")
        self.repo_dir = config.get("repo_dir", "/tmp/angler-git-repo")

        # Inject GitHub token for private repos
        github_token = config.get("github_token", os.environ.get("GITHUB_TOKEN", ""))
        if github_token and "github.com" in self.repo_url:
            self.repo_url = self.repo_url.replace(
                "https://github.com",
                f"https://x-access-token:{github_token}@github.com",
            )

    def _clone_or_pull(self):
        if not self.repo_url:
            raise ValueError("git source requires repo_url")
        if Path(self.repo_dir).exists():
            repo = Repo(self.repo_dir)
            repo.remotes.origin.pull()
        else:
            Repo.clone_from(self.repo_url, self.repo_dir)

    def fetch_documents(self) -> list[Document]:
        self._clone_or_pull()
        documents = []

        for md_file in Path(self.repo_dir).rglob("*.md"):
            # Skip dotfiles/dirs
            if any(part.startswith(".") for part in md_file.relative_to(self.repo_dir).parts):
                continue

            post = frontmatter.load(str(md_file))
            if not post.content.strip():
                continue

            rel_path = str(md_file.relative_to(self.repo_dir))
            documents.append(Document(
                id=f"git://{rel_path}",
                content=post.content,
                metadata={
                    "source": "git",
                    "path": rel_path,
                    "title": post.get("title", md_file.stem),
                    **{k: str(v) for k, v in post.metadata.items()},
                },
            ))

        return documents
