"""
Shared test fixtures for all test modules.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def test_session(test_db):
    Session = sessionmaker(bind=test_db)
    session = Session()
    try:
        yield session
    finally:
        session.close()
