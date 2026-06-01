import os
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event
from sqlalchemy.engine import Engine

from src.models import Base, TestSession

# Setup database path ensuring local-first execution
DB_DIR = os.path.join(os.getcwd(), "UPSC_Agent_Data")
os.makedirs(DB_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'hub_database.db')}"

# Create engine. SQLite needs check_same_thread=False for FastAPI concurrency.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# Enable SQLite WAL (Write-Ahead Logging) mode for better concurrency performance
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_session():
    """Dependency for yielding database sessions."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def init_db():
    """Initializes the database by creating all defined tables."""
    Base.metadata.create_all(bind=engine)

def expire_stale_sessions(timeout_minutes: int = 120):
    """
    Utility function to expire test sessions that have exceeded the inactivity timeout.
    This handles the session scoping behavior defined in Q4.
    """
    session = SessionLocal()
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        # Find active sessions whose last activity is older than cutoff
        stale_sessions = session.query(TestSession).filter(
            TestSession.session_status == "ACTIVE",
            TestSession.last_activity_at < cutoff_time
        ).all()
        
        for ts in stale_sessions:
            ts.session_status = "EXPIRED"
            
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
