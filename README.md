# Angler

Semantic search for your markdown content. Point it at a git repo full of markdown files and get a search API powered by ChromaDB embeddings.

## What it does

Angler clones your markdown repo, chunks the content, generates embeddings, and serves a search API. It finds content by meaning, not just keywords — so searching "what did we discuss about pricing" will find relevant passages even if they never use the word "pricing."

## Quick start

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REPO_URL` | Yes | Git URL of your markdown repo |
| `GITHUB_TOKEN` | No | For private GitHub repos |
| `CHROMA_DIR` | No | Where to persist the index (default: `/data/chroma`) |
| `PORT` | No | Server port (default: `8000`) |

### Run locally

```bash
REPO_URL=https://github.com/yourorg/your-docs.git uvicorn app:app --reload
```

### Deploy to Railway

1. Fork this repo
2. Connect it to Railway
3. Set `REPO_URL` and `GITHUB_TOKEN` (if private) as env vars
4. Railway will use the included `Dockerfile` and `railway.toml`

## API

### `GET /search?q=your+query&n=5`

Search your content. Returns ranked results with relevance scores.

```json
{
  "query": "your query",
  "results": [
    {
      "id": "docs/meeting-notes.md::chunk_3",
      "score": 0.82,
      "content": "...matching text...",
      "metadata": {
        "path": "docs/meeting-notes.md",
        "title": "Meeting Notes"
      }
    }
  ]
}
```

### `POST /reindex`

Re-pull the repo and rebuild the index.

### `GET /health`

Check service status and index size.

## How it works

1. Clones/pulls your git repo on startup
2. Parses all `.md` files (supports frontmatter metadata)
3. Chunks text into ~500 char overlapping segments
4. Stores chunks + embeddings in ChromaDB
5. Queries use cosine similarity against ChromaDB's default embedding model

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

Then use `/search-docs` in Claude Code to search your content.

## License

MIT
