import os
import threading
import chromadb
from fastapi import FastAPI, Query

from config import load_config
from sources import SOURCE_TYPES

app = FastAPI(title="Angler", description="Semantic search for your content")
indexing_status = {"running": False, "error": None}

CHROMA_DIR = os.environ.get("CHROMA_DIR", "/data/chroma")
client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = client.get_or_create_collection(
    name="content",
    metadata={"hnsw:space": "cosine"},
)


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
    config = load_config()
    sources = config.get("sources", [])

    if not sources:
        raise ValueError("No sources configured. Set ANGLER_CONFIG or source env vars.")

    # Clear existing index
    existing = collection.count()
    if existing > 0:
        all_ids = collection.get()["ids"]
        collection.delete(ids=all_ids)

    all_ids = []
    all_docs = []
    all_meta = []

    for source_config in sources:
        source_type = source_config.get("type")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"Unknown source type: {source_type}")

        source = SOURCE_TYPES[source_type](source_config)
        documents = source.fetch_documents()

        for doc in documents:
            chunks = chunk_text(doc.content)
            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc.id}::chunk_{i}"
                all_ids.append(chunk_id)
                all_docs.append(chunk)
                all_meta.append(doc.metadata)

    # ChromaDB has a batch limit
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
    config = load_config()
    if collection.count() == 0 and config.get("sources"):
        threading.Thread(target=_background_index, daemon=True).start()


@app.get("/search")
def search(
    q: str = Query(..., description="Search query"),
    n: int = Query(10, description="Number of results"),
    source: str | None = Query(None, description="Filter by source type"),
):
    kwargs = {"query_texts": [q], "n_results": n}
    if source:
        kwargs["where"] = {"source": source}

    results = collection.query(**kwargs)
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
    config = load_config()
    source_types = [s.get("type") for s in config.get("sources", [])]
    status = "indexing" if indexing_status["running"] else "ok"
    if indexing_status["error"]:
        status = "error"
    return {
        "status": status,
        "sources": source_types,
        "indexed_chunks": collection.count(),
        "error": indexing_status["error"],
    }
