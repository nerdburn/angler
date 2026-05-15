import os
import yaml
from pathlib import Path


def load_config() -> dict:
    """Load config from angler.yaml or fall back to env vars."""
    config_path = Path(os.environ.get("ANGLER_CONFIG", "angler.yaml"))

    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)

    # Fall back to env vars for simple single-source deployments
    config = {"sources": []}

    if os.environ.get("REPO_URL"):
        config["sources"].append({
            "type": "git",
            "repo_url": os.environ["REPO_URL"],
        })

    if os.environ.get("NOTION_TOKEN"):
        source = {"type": "notion", "token": os.environ["NOTION_TOKEN"]}
        if os.environ.get("NOTION_DATABASES"):
            source["databases"] = os.environ["NOTION_DATABASES"].split(",")
        config["sources"].append(source)

    if os.environ.get("GOOGLE_DOCS_FOLDER_ID"):
        config["sources"].append({
            "type": "google_docs",
            "folder_id": os.environ["GOOGLE_DOCS_FOLDER_ID"],
        })

    return config
