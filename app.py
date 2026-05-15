import json
import os
import time
import uuid
import threading
import chromadb
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Query

from config import load_config
from sources import SOURCE_TYPES

app = FastAPI(title="Angler", description="Semantic search for your content")

CHROMA_DIR = os.environ.get("CHROMA_DIR", "/data/chroma")
STATE_FILE = os.path.join(CHROMA_DIR, "angler_state.json")
chroma = chromadb.PersistentClient(path=CHROMA_DIR)

# The live collection that search queries hit
live_collection = chroma.get_or_create_collection(
    name="content",
    metadata={"hnsw:space": "cosine"},
)

# Indexing state
indexing_state = {
    "running": False,
    "job_id": None,
    "error": None,
    "started_at": None,
    "completed_at": None,
    "chunks_indexed": 0,
    "source_progress": {},
}
_index_lock = threading.Lock()


def _load_persistent_state() -> dict:
    """Load last_indexed timestamps from disk."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def _save_persistent_state(state: dict):
    """Save last_indexed timestamps to disk."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


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


def _build_index(job_id: str, full: bool = False):
    """Build or update the index. Uses shadow collection for full rebuilds, upserts for incremental."""

    shadow_name = f"content_shadow_{job_id}"
    persistent_state = _load_persistent_state()

    try:
        config = load_config()
        sources = config.get("sources", [])

        if not sources:
            raise ValueError("No sources configured.")

        is_incremental = not full and live_collection.count() > 0

        if is_incremental:
            # Incremental: upsert changed docs directly into live collection
            target = live_collection
        else:
            # Full: build into shadow, then swap
            target = chroma.get_or_create_collection(
                name=shadow_name,
                metadata={"hnsw:space": "cosine"},
            )

        total_chunks = 0

        for source_config in sources:
            source_type = source_config.get("type")
            if source_type not in SOURCE_TYPES:
                raise ValueError(f"Unknown source type: {source_type}")

            # Get last indexed time for incremental
            since = None
            if is_incremental:
                last_indexed = persistent_state.get(f"last_indexed_{source_type}")
                if last_indexed:
                    since = datetime.fromisoformat(last_indexed)

            indexing_state["source_progress"][source_type] = "fetching" + (" (incremental)" if since else "")
            source = SOURCE_TYPES[source_type](source_config)
            documents = source.fetch_documents(since=since)

            indexing_state["source_progress"][source_type] = f"chunking {len(documents)} docs"

            all_ids = []
            all_docs = []
            all_meta = []

            for doc in documents:
                # For incremental: remove old chunks for this doc before adding new ones
                if is_incremental:
                    old_ids = target.get(
                        where={"source": source_type},
                        include=[],
                    )["ids"]
                    doc_prefix = f"{doc.id}::chunk_"
                    stale = [oid for oid in old_ids if oid.startswith(doc_prefix)]
                    if stale:
                        target.delete(ids=stale)

                chunks = chunk_text(doc.content)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{doc.id}::chunk_{i}"
                    all_ids.append(chunk_id)
                    all_docs.append(chunk)
                    all_meta.append(doc.metadata)

            # Add in batches
            batch_size = 500
            for i in range(0, len(all_ids), batch_size):
                target.upsert(
                    ids=all_ids[i : i + batch_size],
                    documents=all_docs[i : i + batch_size],
                    metadatas=all_meta[i : i + batch_size],
                )

            total_chunks += len(all_ids)

            # Update last indexed timestamp for this source
            persistent_state[f"last_indexed_{source_type}"] = datetime.now(timezone.utc).isoformat()
            indexing_state["source_progress"][source_type] = "done"

        # For full rebuild: swap shadow into live
        if not is_incremental:
            existing = live_collection.count()
            if existing > 0:
                old_ids = live_collection.get()["ids"]
                live_collection.delete(ids=old_ids)

            total = target.count()
            for offset in range(0, total, batch_size):
                batch = target.get(
                    limit=batch_size,
                    offset=offset,
                    include=["documents", "metadatas"],
                )
                if batch["ids"]:
                    live_collection.add(
                        ids=batch["ids"],
                        documents=batch["documents"],
                        metadatas=batch["metadatas"],
                    )

        _save_persistent_state(persistent_state)
        indexing_state["chunks_indexed"] = total_chunks
        indexing_state["completed_at"] = time.time()

    except Exception as e:
        indexing_state["error"] = str(e)
    finally:
        indexing_state["running"] = False
        indexing_state["source_progress"] = {}
        try:
            chroma.delete_collection(shadow_name)
        except Exception:
            pass


def start_reindex(full: bool = False) -> str:
    """Kick off a background reindex. Returns job ID."""
    if not _index_lock.acquire(blocking=False):
        return indexing_state.get("job_id", "")

    try:
        job_id = uuid.uuid4().hex[:8]
        indexing_state.update({
            "running": True,
            "job_id": job_id,
            "error": None,
            "started_at": time.time(),
            "completed_at": None,
            "chunks_indexed": 0,
            "source_progress": {},
        })
        threading.Thread(target=_build_index, args=(job_id, full), daemon=True).start()
        return job_id
    finally:
        _index_lock.release()


@app.on_event("startup")
def startup():
    config = load_config()
    if live_collection.count() == 0 and config.get("sources"):
        start_reindex(full=True)


@app.get("/search")
def search(
    q: str = Query(..., description="Search query"),
    n: int = Query(10, description="Number of results"),
    source: str | None = Query(None, description="Filter by source type"),
):
    if live_collection.count() == 0:
        return {"query": q, "results": [], "status": "index_empty"}

    kwargs = {"query_texts": [q], "n_results": n}
    if source:
        kwargs["where"] = {"source": source}

    results = live_collection.query(**kwargs)
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
def reindex(full: bool = Query(False, description="Force full reindex instead of incremental")):
    if indexing_state["running"]:
        return {
            "status": "already_running",
            "job_id": indexing_state["job_id"],
            "source_progress": indexing_state["source_progress"],
        }

    job_id = start_reindex(full=full)
    return {"status": "started", "job_id": job_id, "mode": "full" if full else "incremental"}


@app.get("/reindex/status")
def reindex_status():
    elapsed = None
    if indexing_state["started_at"]:
        end = indexing_state["completed_at"] or time.time()
        elapsed = round(end - indexing_state["started_at"], 1)

    return {
        "running": indexing_state["running"],
        "job_id": indexing_state["job_id"],
        "elapsed_seconds": elapsed,
        "chunks_indexed": indexing_state["chunks_indexed"],
        "source_progress": indexing_state["source_progress"],
        "error": indexing_state["error"],
    }


@app.get("/health")
def health():
    config = load_config()
    source_types = [s.get("type") for s in config.get("sources", [])]
    status = "indexing" if indexing_state["running"] else "ok"
    if indexing_state["error"]:
        status = "error"
    return {
        "status": status,
        "sources": source_types,
        "indexed_chunks": live_collection.count(),
        "error": indexing_state["error"],
    }
