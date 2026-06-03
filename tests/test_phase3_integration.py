"""Phase 3 Integration Verification tests."""

import os
import asyncio
import tempfile
import pytest
import sys
import inspect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.models import Base, StudentProfile, TopicProgress, BacklogQueue, QuestionBank, AttemptHistory
from src import generator, evaluator

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
    
    orig_gen_session = generator.SessionLocal
    orig_eval_session = evaluator.SessionLocal
    
    generator.SessionLocal = Session
    evaluator.SessionLocal = Session

    # Setup basic state needed
    sess = Session()
    profile = StudentProfile(subject_id="GS1", subject_name="General Studies 1", current_elo_rating=1200)
    sess.add(profile)
    sess.commit()
    sess.close()

    yield engine, Session

    generator.SessionLocal = orig_gen_session
    evaluator.SessionLocal = orig_eval_session
    os.unlink(db_path)


@pytest.mark.asyncio
class TestGenerateEvaluateFlow:

    async def test_end_to_end_pipeline(self, test_env):
        engine, Session = test_env
        gen_pipe = generator.GeneratorPipeline()
        eval_pipe = evaluator.EvaluationPipeline()
        
        # Override composition slightly for speed
        from unittest.mock import patch
        with patch.object(gen_pipe, 'generate_composition') as mock_comp:
            from src.composition_engine import CompositionPlan
            mock_comp.return_value = CompositionPlan(
                target_total=2, floor_count=0, static_today=2, static_backlog=0, ca_today=0, ca_backlog=0
            )
            
            plan, results = await gen_pipe.execute_generation_pipeline(subject_id="GS1", mode="DAILY_SPRINT")
            
        assert len(results) == 2
        
        sess = Session()
        db_q = sess.query(QuestionBank).first()
        sess.close()
            
        eval_res = await eval_pipe.evaluate_answer(db_q.question_id, "session_123", db_q.correct_key or "A")
        
        assert "normalized_score" in eval_res
        assert "critic_verification" in eval_res
        
        # Verify persistence
        sess = Session()
        attempts = sess.query(AttemptHistory).all()
        sess.close()
        
        assert len(attempts) == 1
        assert attempts[0].question_id == db_q.question_id


@pytest.mark.asyncio
class TestFailureRecovery:

    async def test_failed_generation_does_not_corrupt_evaluator(self, test_env):
        engine, Session = test_env
        gen_pipe = generator.GeneratorPipeline()
        eval_pipe = evaluator.EvaluationPipeline()
        
        # Mock catastrophic generation failure
        from unittest.mock import patch
        with patch.object(gen_pipe, 'persist_generated_batch', side_effect=Exception("DB Down")):
            with pytest.raises(Exception):
                await gen_pipe.execute_generation_pipeline(subject_id="GS1", mode="DAILY_SPRINT")
                
        # Evaluator should still work if we add a manual question
        sess = Session()
        q = QuestionBank(
            question_id="manual_q", subject_id="GS1", source_type="STATIC",
            question_type="PRELIMS_GS", difficulty_level=1, question_text="X?",
            metadata_json={"blueprint": "yes"}, correct_key="A", provenance_tags={}
        )
        sess.add(q)
        sess.commit()
        sess.close()
        
        res = await eval_pipe.evaluate_answer("manual_q", "sess2", "A")
        assert res["normalized_score"] == 1.0


class TestBoundaryValidation:

    def test_evaluator_independent_of_generator(self):
        source = inspect.getsource(sys.modules["src.evaluator"]) if "src.evaluator" in sys.modules else inspect.getsource(evaluator)
        assert "generator" not in source

    def test_generator_independent_of_evaluator(self):
        source = inspect.getsource(sys.modules["src.generator"]) if "src.generator" in sys.modules else inspect.getsource(generator)
        assert "evaluator" not in source
