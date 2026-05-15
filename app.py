import os
import shutil
import threading
import frontmatter
import chromadb
from pathlib import Path
from git import Repo
from fastapi import FastAPI, Query

app = FastAPI(title="Angler", description="Semantic search for your markdown content")
indexing_status = {"running": False, "error": None}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_URL = os.environ.get("REPO_URL", "")
if GITHUB_TOKEN and REPO_URL and "github.com" in REPO_URL:
    # Inject token for private repos
    REPO_URL = REPO_URL.replace(
        "https://github.com",
        f"https://x-access-token:{GITHUB_TOKEN}@github.com",
    )
REPO_DIR = "/tmp/content-repo"
CHROMA_DIR = os.environ.get("CHROMA_DIR", "/data/chroma")

client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = client.get_or_create_collection(
    name="markdown_content",
    metadata={"hnsw:space": "cosine"},
)


def clone_or_pull():
    if not REPO_URL:
        raise ValueError("REPO_URL environment variable is required")
    if Path(REPO_DIR).exists():
        repo = Repo(REPO_DIR)
        repo.remotes.origin.pull()
    else:
        Repo.clone_from(REPO_URL, REPO_DIR)


def parse_markdown(file_path: Path) -> dict:
    post = frontmatter.load(str(file_path))
    rel_path = str(file_path.relative_to(REPO_DIR))
    return {
        "id": rel_path,
        "content": post.content,
        "metadata": {
            "path": rel_path,
            "title": post.get("title", file_path.stem),
            **{k: str(v) for k, v in post.metadata.items()},
        },
    }


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def index_all():
    clone_or_pull()
    md_files = list(Path(REPO_DIR).rglob("*.md"))

    existing = collection.count()
    if existing > 0:
        all_ids = collection.get()["ids"]
        collection.delete(ids=all_ids)

    all_ids = []
    all_docs = []
    all_meta = []

    for md_file in md_files:
        if any(part.startswith(".") for part in md_file.relative_to(REPO_DIR).parts):
            continue

        parsed = parse_markdown(md_file)
        if not parsed["content"].strip():
            continue

        chunks = chunk_text(parsed["content"])
        for i, chunk in enumerate(chunks):
            chunk_id = f"{parsed['id']}::chunk_{i}"
            all_ids.append(chunk_id)
            all_docs.append(chunk)
            all_meta.append(parsed["metadata"])

    batch_size = 500
    for i in range(0, len(all_ids), batch_size):
        collection.add(
            ids=all_ids[i : i + batch_size],
            documents=all_docs[i : i + batch_size],
            metadatas=all_meta[i : i + batch_size],
        )

    return len(all_ids)


def _background_index():
    indexing_status["running"] = True
    try:
        index_all()
    except Exception as e:
        indexing_status["error"] = str(e)
    finally:
        indexing_status["running"] = False


@app.on_event("startup")
def startup():
    if collection.count() == 0 and REPO_URL:
        threading.Thread(target=_background_index, daemon=True).start()


@app.get("/search")
def search(
    q: str = Query(..., description="Search query"),
    n: int = Query(10, description="Number of results"),
):
    results = collection.query(query_texts=[q], n_results=n)
    hits = []
    for i, doc_id in enumerate(results["ids"][0]):
        hits.append(
            {
                "id": doc_id,
                "score": 1 - results["distances"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
            }
        )
    return {"query": q, "results": hits}


@app.post("/reindex")
def reindex():
    count = index_all()
    return {"status": "ok", "chunks_indexed": count}


@app.get("/health")
def health():
    status = "indexing" if indexing_status["running"] else "ok"
    if indexing_status["error"]:
        status = "error"
    return {
        "status": status,
        "indexed_chunks": collection.count(),
        "error": indexing_status["error"],
    }
