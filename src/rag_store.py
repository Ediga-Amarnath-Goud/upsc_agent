"""
RAG Store Module (Phase 2 Group 1)
Manages the ChromaDB collections for syllabus and PYQs using sentence-transformers.
"""

import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

import chromadb
from chromadb.errors import NotFoundError
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# --- Singleton Embedding Lifecycle ---
_embedding_model: Optional[SentenceTransformer] = None

def get_embedding_model() -> SentenceTransformer:
    """
    Lazily loads the sentence-transformers model as a Singleton.
    Prevents repeated memory allocation and initialization latency.
    """
    global _embedding_model
    if _embedding_model is None:
        logger.info("Initializing sentence-transformers/all-MiniLM-L6-v2 singleton...")
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


# --- ChromaDB Client ---
# Machine-agnostic path relative to the project root
DB_PATH = Path(__file__).parent.parent / ".chroma_db"

def get_chroma_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=str(DB_PATH))

# --- Explicit Idempotent Collection Initialization ---
def initialize_collections():
    """
    Creates the required collections idempotently if they do not exist.
    """
    client = get_chroma_client()
    # Explicitly idempotent method: safe to call multiple times
    client.get_or_create_collection(name="syllabus_collection")
    client.get_or_create_collection(name="pyq_collection")
    logger.info("ChromaDB collections initialized idempotently.")


# --- Ingestion with Metadata and Hash IDs ---
def _generate_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def ingest_syllabus_documents(documents: List[str]):
    """
    Ingests syllabus chunks with idempotent upserts and structured metadata contracts.
    """
    if not documents:
        return
        
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="syllabus_collection")
    model = get_embedding_model()
    
    ids = []
    embeddings = []
    metadatas = []
    
    for doc in documents:
        doc_id = _generate_id(doc)
        ids.append(doc_id)
        embeddings.append(model.encode(doc).tolist())
        metadatas.append({
            "source": "syllabus",
            "ingested_at": datetime.now(timezone.utc).isoformat()
        })
        
    # Upsert guarantees safe reruns without duplicating vectors
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas
    )
    logger.info(f"Upserted {len(documents)} syllabus documents securely.")

def ingest_pyq_documents(documents: List[str]):
    """
    Ingests PYQ chunks with idempotent upserts and structured metadata contracts.
    """
    if not documents:
        return
        
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="pyq_collection")
    model = get_embedding_model()
    
    ids = []
    embeddings = []
    metadatas = []
    
    for doc in documents:
        doc_id = _generate_id(doc)
        ids.append(doc_id)
        embeddings.append(model.encode(doc).tolist())
        metadatas.append({
            "source": "pyq",
            "ingested_at": datetime.now(timezone.utc).isoformat()
        })
        
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas
    )
    logger.info(f"Upserted {len(documents)} PYQ documents securely.")


# --- Structured Retrieval Contracts with Narrow Exceptions ---
def retrieve_syllabus_chunks(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieves nearest syllabus chunks.
    Returns a structured contract: [{"id": str, "text": str, "metadata": dict, "distance": float}, ...]
    """
    return _retrieve_from_collection("syllabus_collection", query, n_results)

def retrieve_similar_pyqs(query: str, n_results: int = 3) -> List[Dict[str, Any]]:
    """
    Retrieves nearest PYQ chunks.
    Returns a structured contract: [{"id": str, "text": str, "metadata": dict, "distance": float}, ...]
    """
    return _retrieve_from_collection("pyq_collection", query, n_results)

def _retrieve_from_collection(collection_name: str, query: str, n_results: int) -> List[Dict[str, Any]]:
    client = get_chroma_client()
    model = get_embedding_model()
    
    try:
        # Use get_collection to explicitly trigger NotFoundError 
        # if the collection hasn't been initialized, avoiding implicit creation during retrieval.
        collection = client.get_collection(name=collection_name)
    except NotFoundError:
        logger.warning(f"Collection {collection_name} does not exist. Returning empty list.")
        return []
    
    # Handle the case where the collection exists but is empty
    if collection.count() == 0:
        return []
        
    query_embedding = model.encode(query).tolist()
    
    # Cap n_results to actual collection size to avoid Chroma warnings
    actual_n = min(n_results, collection.count())
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=actual_n
    )
    
    structured_results = []
    if not results or not results.get("documents") or not results["documents"][0]:
        return structured_results
        
    for i in range(len(results["documents"][0])):
        doc_text = results["documents"][0][i]
        doc_id = results["ids"][0][i]
        doc_meta = results["metadatas"][0][i] if results.get("metadatas") else {}
        distance = results["distances"][0][i] if results.get("distances") else 0.0
        
        structured_results.append({
            "id": doc_id,
            "text": doc_text,
            "metadata": doc_meta,
            "distance": distance
        })
        
    return structured_results
