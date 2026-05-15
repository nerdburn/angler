# Angler

Semantic search for your company's content. Connect your markdown repos, Notion workspace, Google Docs, and Dropbox — then search everything with a single API.

## What it does

Angler pulls content from multiple sources, chunks it, generates embeddings, and serves a search API powered by ChromaDB. It finds content by meaning, not just keywords — so searching "what did we discuss about pricing" will find relevant passages even if they never use the word "pricing."

## Sources

| Source | What it indexes | Auth |
|--------|----------------|------|
| **Git** | Markdown files from a git repo | GitHub token (for private repos) |
| **Notion** | Pages and database entries | Internal integration token |
| **Google Docs** | Documents in a Drive folder | Service account credentials |
| **Dropbox** | Text files in a Dropbox folder | Access token |

## Quick start

### Option 1: Config file

Copy `angler.yaml.example` to `angler.yaml` and enable the sources you need:

```yaml
sources:
  - type: git
    repo_url: https://github.com/yourorg/docs.git

  - type: notion
    # token set via NOTION_TOKEN env var

  - type: google_docs
    folder_id: "1a2b3c..."

  - type: dropbox
    # token set via DROPBOX_TOKEN env var
    folder_path: "/Documents"  # optional, "" = root
```

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

### Option 2: Environment variables

For simple deployments, skip the config file and use env vars:

| Variable | Source | Description |
|----------|--------|-------------|
| `REPO_URL` | Git | URL of your markdown repo |
| `GITHUB_TOKEN` | Git | For private GitHub repos |
| `NOTION_TOKEN` | Notion | Internal integration token |
| `NOTION_DATABASES` | Notion | Comma-separated database IDs (optional) |
| `GOOGLE_DOCS_FOLDER_ID` | Google Docs | Root folder to index |
| `GOOGLE_CREDENTIALS_JSON` | Google Docs | Service account JSON |
| `DROPBOX_TOKEN` | Dropbox | App access token |
| `DROPBOX_FOLDER_PATH` | Dropbox | Folder to index (optional, default: root) |
| `CHROMA_DIR` | — | Where to persist the index (default: `/data/chroma`) |
| `PORT` | — | Server port (default: `8000`) |

### Deploy to Railway

1. Fork this repo
2. Connect it to Railway
3. Set your source env vars
4. Railway will use the included `Dockerfile` and `railway.toml`

## API

### `GET /search?q=your+query&n=5`

Search your content. Returns ranked results with relevance scores.

```json
{
  "query": "your query",
  "results": [
    {
      "id": "git://docs/meeting-notes.md::chunk_3",
      "score": 0.82,
      "content": "...matching text...",
      "metadata": {
        "source": "git",
        "path": "docs/meeting-notes.md",
        "title": "Meeting Notes"
      }
    }
  ]
}
```

Filter by source type:

```
GET /search?q=pricing+discussion&source=notion
```

### `POST /reindex`

Re-fetch all sources and rebuild the index.

### `GET /health`

Check service status, configured sources, and index size.

## Source setup

### Git

Just set `REPO_URL`. For private repos, also set `GITHUB_TOKEN`.

### Notion

1. Create an internal integration at [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Copy the integration token
3. Share your top-level workspace pages with the integration (this grants access to all child pages)
4. Set `NOTION_TOKEN`

### Google Docs

1. Create a service account in Google Cloud Console
2. Enable the Google Drive and Google Docs APIs
3. Share your target folder with the service account's email address
4. Set `GOOGLE_DOCS_FOLDER_ID` and `GOOGLE_CREDENTIALS_JSON`

### Dropbox

1. Create an app at [dropbox.com/developers/apps](https://www.dropbox.com/developers/apps)
2. Generate an access token
3. Set `DROPBOX_TOKEN` and optionally `DROPBOX_FOLDER_PATH`

By default it indexes `.md`, `.txt`, `.csv`, `.json`, `.yaml`, `.xml`, `.html`, and `.rtf` files. You can customize this with the `extensions` config option.

## Using with Claude Code

Create a skill at `~/.claude/skills/search-docs/SKILL.md`:

```markdown
---
name: search-docs
description: Search our team's docs, notes, and knowledge base.
user_invocable: true
---

Use the Bash tool to query the search API:

\```bash
curl -s "https://your-deployment.up.railway.app/search?q=QUERY&n=5" | python3 -m json.tool
\```
```

Then use `/search-docs` in Claude Code to search your content naturally.

## License

MIT
