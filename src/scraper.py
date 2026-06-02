"""
Data Scraper Module (Phase 2 Group 2)
Handles Tier 1, Tier 2, and Tier 3 data ingestion, consensus filtering, deduplication, and AI synthesis.
Strictly isolated from rag_store.py.
"""

import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import numpy as np

from sqlalchemy import text
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from src.database import engine, get_session
from src.models import CurrentAffairsFeed
from src.calibration import get_config

logger = logging.getLogger(__name__)

# --- Local Embedding Singleton (C-07 Isolation) ---
_embedding_model: Optional[SentenceTransformer] = None

def _get_embedding_model() -> SentenceTransformer:
    """Lazily loads the local sentence-transformer for deduplication."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("Initializing local SentenceTransformer for scraper deduplication...")
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


# --- SQLite Staging Cache Management ---
def _initialize_staging_table(conn):
    """
    Creates a connection-scoped SQLite TEMP TABLE.
    Guarantees concurrency isolation, avoids global locks, and safely auto-drops on disconnect.
    Uses IF NOT EXISTS and DELETE to survive Pytest shared in-memory connection pools.
    """
    conn.execute(text("""
        CREATE TEMP TABLE IF NOT EXISTS scraper_staging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            source_name TEXT,
            source_type TEXT
        )
    """))
    conn.execute(text("DELETE FROM scraper_staging"))
    logger.debug("Connection-scoped staging TEMP table initialized and cleared.")


# --- Synthesis Pipeline ---
def _mock_cloud_api_synthesis(content: str) -> str:
    """Mock Cloud API for AI synthesis (to be replaced with actual LLM calls)."""
    return f"AI Synthesized Summary: {content[:100]}..."

def _synthesize_article(content: str) -> Dict[str, str]:
    """
    Graceful degradation wrapper for AI synthesis.
    Returns a structured dictionary to track explicit synthesis_status.
    """
    if not content.strip():
        return {"synthesis_status": "SKIPPED", "text": ""}
        
    try:
        # Simulate network API call
        synthesis_text = _mock_cloud_api_synthesis(content)
        return {"synthesis_status": "SUCCESS", "text": synthesis_text}
    except Exception as e:
        logger.warning(f"Cloud API synthesis failed: {e}. Degrading gracefully and writing raw article.")
        return {"synthesis_status": "FAILED", "text": ""}

def _write_to_feed(title: str, content: str, source_name: str, source_type: str, synthesis_data: Dict[str, str]):
    """Writes the finalized article to the Phase 1 database."""
    db = next(get_session())
    try:
        # Serialize synthesis_status explicitly inside the text field to respect Phase 1 schema immutability
        ai_synthesis_serialized = json.dumps(synthesis_data)
        
        feed = CurrentAffairsFeed(
            article_id=str(uuid.uuid4()),
            source=source_name,
            title=title,
            raw_content=content,
            ai_synthesis=ai_synthesis_serialized
        )
        db.add(feed)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database write failed for feed: {e}")
    finally:
        db.close()


# --- Core Pipeline Execution ---
def _process_staging_pipeline(conn, require_consensus: bool = True):
    """
    Reads from the connection-scoped staging table, applies consensus filtering, deduplicates 
    against a bounded rolling window in the DB, synthesizes content, and commits.
    """
    config = get_config().current_affairs_filters
    similarity_threshold = config.get('similarity_threshold', 0.88)
    min_consensus = config.get('min_source_consensus', 2)
    # Fallback to 48 hours if rolling_window_hours isn't strictly defined in older configs
    rolling_window = config.get('rolling_window_hours', 48)
    
    rows = conn.execute(text("SELECT id, title, content, source_name, source_type FROM scraper_staging")).fetchall()
    
    if not rows:
        return
        
    model = _get_embedding_model()
    embeddings = model.encode([row.content for row in rows])
    
    valid_indices = set()
    
    # 1. Consensus Filter
    if require_consensus and len(rows) > 0:
        sim_matrix = cosine_similarity(embeddings)
        for i in range(len(rows)):
            matches = sum(1 for j in range(len(rows)) if sim_matrix[i][j] >= similarity_threshold)
            if matches >= min_consensus:
                valid_indices.add(i)
            else:
                logger.info(f"Article '{rows[i].title}' dropped due to lack of consensus ({matches}/{min_consensus}).")
    else:
        valid_indices = set(range(len(rows)))
        
    if not valid_indices:
        return
        
    # 2. Deduplication against bounded existing database window
    date_threshold = datetime.now(timezone.utc) - timedelta(hours=rolling_window)
    db = next(get_session())
    try:
        # Bounded retrieval: Prevents O(N^2) memory explosions by strictly limiting to recent history
        existing_feeds = db.query(CurrentAffairsFeed).filter(
            CurrentAffairsFeed.fetched_at >= date_threshold
        ).all()
        
        existing_embeddings = []
        if existing_feeds:
            existing_embeddings = model.encode([f.raw_content for f in existing_feeds])
    finally:
        db.close()
        
    # 3. Synthesis & Write
    for i in valid_indices:
        row = rows[i]
        
        is_duplicate = False
        if len(existing_embeddings) > 0:
            sims = cosine_similarity([embeddings[i]], existing_embeddings)[0]
            if max(sims) >= similarity_threshold:
                is_duplicate = True
                logger.info(f"Article '{row.title}' dropped as duplicate (similarity: {max(sims):.2f}).")
                
        if not is_duplicate:
            synthesis_data = _synthesize_article(row.content)
            _write_to_feed(
                title=row.title,
                content=row.content,
                source_name=row.source_name,
                source_type=row.source_type,
                synthesis_data=synthesis_data
            )


# --- Public Entrypoints ---
def daily_news_scraper(mock_articles: List[Dict[str, str]] = None):
    """
    Tier 1 and Tier 2 daily news scraper.
    Utilizes connection-scoped TEMP tables for robust concurrency.
    """
    # Open a single connection context for the entire pipeline
    with engine.connect() as conn:
        with conn.begin():
            _initialize_staging_table(conn)
            
            articles = mock_articles or []
            for art in articles:
                conn.execute(
                    text("INSERT INTO scraper_staging (title, content, source_name, source_type) VALUES (:title, :content, :source_name, :source_type)"),
                    {
                        "title": art.get("title", "Untitled"),
                        "content": art.get("content", ""),
                        "source_name": art.get("source_name", "Unknown"),
                        "source_type": art.get("source_type", "Tier 2")
                    }
                )
            
            _process_staging_pipeline(conn, require_consensus=True)
            # The TEMP table is automatically dropped when the connection closes.


def document_ingestor(url: str, source_type: str, mock_content: str = ""):
    """
    Tier 3 event-triggered document ingestor.
    Bypasses consensus filter but maintains connection isolation.
    """
    with engine.connect() as conn:
        with conn.begin():
            _initialize_staging_table(conn)
            
            conn.execute(
                text("INSERT INTO scraper_staging (title, content, source_name, source_type) VALUES (:title, :content, :source_name, :source_type)"),
                {
                    "title": f"Doc from {url}",
                    "content": mock_content,
                    "source_name": url,
                    "source_type": source_type
                }
            )
                
            _process_staging_pipeline(conn, require_consensus=False)
