"""Architecture-first verification tests for Phase 3 Group 3: Evaluator."""

import os
import inspect
import sys
import tempfile
import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import evaluator
from src.models import Base, QuestionBank, AttemptHistory
from src.evaluator import EvaluationPipeline

@pytest.fixture
def test_env():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name

    engine = create_engine(
        f"sqlite:///{db_path}", poolclass=NullPool,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    orig_session_local = evaluator.SessionLocal
    evaluator.SessionLocal = Session

    # Setup basic state needed for evaluator
    sess = Session()
    q_mcq = QuestionBank(
        question_id="q1", subject_id="GS1", source_type="STATIC",
        question_type="PRELIMS_GS", difficulty_level=1, question_text="What is X?",
        metadata_json={"blueprint": "yes"}, correct_key="A", provenance_tags={}
    )
    q_mains = QuestionBank(
        question_id="q2", subject_id="GS1", source_type="STATIC",
        question_type="MAINS_SUBJECTIVE", difficulty_level=5, question_text="Discuss Y.",
        metadata_json={"blueprint": "yes"}, correct_key=None, provenance_tags={}
    )
    q_missing_meta = QuestionBank(
        question_id="q3", subject_id="GS1", source_type="STATIC",
        question_type="PRELIMS_GS", difficulty_level=1, question_text="What is Z?",
        metadata_json={}, correct_key="A", provenance_tags={} # Empty metadata json
    )
    sess.add_all([q_mcq, q_mains, q_missing_meta])
    sess.commit()
    sess.close()

    yield engine, Session

    evaluator.SessionLocal = orig_session_local
    os.unlink(db_path)

@pytest.fixture
def mock_pipeline():
    return EvaluationPipeline()

@pytest.mark.asyncio
class TestEvaluatorLogic:

    async def test_blueprint_lookup_failure(self, test_env, mock_pipeline):
        with pytest.raises(ValueError, match="not found"):
            await mock_pipeline.evaluate_answer("invalid_id", "s1", "A")

    async def test_missing_blueprint_behavior(self, test_env, mock_pipeline):
        with pytest.raises(ValueError, match="missing blueprint"):
            await mock_pipeline.evaluate_answer("q3", "s1", "A")

    async def test_mcq_deterministic_scoring(self, test_env, mock_pipeline):
        res1 = await mock_pipeline.evaluate_answer("q1", "s1", "A")
        assert res1["raw_score"] == 1.0
        assert res1["normalized_score"] == 1.0

        res2 = await mock_pipeline.evaluate_answer("q1", "s1", "B")
        assert res2["raw_score"] == 0.0
        assert res2["normalized_score"] == 0.0

    async def test_mains_weighting_behavior(self, test_env, mock_pipeline):
        res = await mock_pipeline.evaluate_answer("q2", "s1", "This is a very long response covering exactly more than ten words.")
        # Given details in structural_evaluate_mains:
        # rel=0.8, cov=0.7, str=0.9, ana=0.85, evi=0.75, con=0.8
        # Weights: 0.25, 0.20, 0.15, 0.20, 0.10, 0.10
        # Expected: 0.2 + 0.14 + 0.135 + 0.17 + 0.075 + 0.08 = 0.8
        assert abs(res["raw_score"] - 0.8) < 0.001

    async def test_normalized_bounds(self, test_env, mock_pipeline):
        # Even if raw score somehow > 1.0, normalize caps it.
        assert mock_pipeline.normalize_score(1.5) == 1.0
        assert mock_pipeline.normalize_score(-0.5) == 0.0

    async def test_rollback_behavior(self, test_env, mock_pipeline):
        engine, Session = test_env
        with patch.object(mock_pipeline, 'persist_evaluation', side_effect=Exception("DB Failure")):
            with pytest.raises(Exception, match="DB Failure"):
                await mock_pipeline.evaluate_answer("q1", "s1", "A")
        
        # Rollback means 0 attempts recorded
        sess = Session()
        # Since the test DB is fresh per fixture, it should have 0 attempts 
        # (the previous tests run on their own fixture instances if they are distinct, 
        # but even if they share, we just check attempt count didn't increment)
        assert sess.query(AttemptHistory).count() == 0
        sess.close()

    async def test_malformed_inputs(self, test_env, mock_pipeline):
        with pytest.raises(ValueError, match="Malformed"):
            await mock_pipeline.evaluate_answer("q2", "s1", "short")


class TestDependencyBoundaries:
    SOURCE = inspect.getsource(sys.modules["src.evaluator"]) if "src.evaluator" in sys.modules else inspect.getsource(evaluator)

    def test_no_generator_import(self):
        assert "src.generator" not in self.SOURCE

    def test_no_rag_store_import(self):
        assert "src.rag_store" not in self.SOURCE

    def test_no_inline_composition_math(self):
        assert "solve_composition" not in self.SOURCE

