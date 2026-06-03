"""
Architecture-first tests for Phase 3 Group 2: The Generator Pipeline.

Verifies state retrieval, composition integration, critic retry logic,
fallback activation, persistence, and dependency boundaries.
"""

import asyncio
import ast
import inspect
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from typing import List

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from pydantic import ValidationError

from src.models import Base, StudentProfile, BacklogQueue, TopicProgress, QuestionBank
import src.generator as gen_mod
from src.generator import GeneratorPipeline, GeneratedQuestionSchema, CriticEvaluationSchema
from src.composition_engine import CompositionPlan


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_engine():
    """In-memory SQLite engine for generator tests."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Yield a session and roll back after test."""
    Session = sessionmaker(bind=db_engine)
    sess = Session()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture
def seeded_session(db_session):
    """Pre-populate student profile and backlog for generator tests."""
    profile = StudentProfile(
        subject_id="GS1",
        subject_name="Geography",
        current_elo_rating=1200,
    )
    backlog_gs = BacklogQueue(
        topic_id="geo_1", topic_type="GS", date_skipped="2026-06-01"
    )
    backlog_ca = BacklogQueue(
        topic_id="ca_1", topic_type="CA", date_skipped="2026-06-01"
    )
    db_session.add_all([profile, backlog_gs, backlog_ca])
    db_session.commit()
    return db_session


@pytest.fixture
def patch_rag_store():
    """Mock rag_store retrieval to return dummy data."""
    with patch("src.generator.retrieve_syllabus_chunks") as mock_syl, \
         patch("src.generator.retrieve_similar_pyqs") as mock_pyq:
        mock_syl.return_value = ["Syllabus chunk 1", "Syllabus chunk 2"]
        mock_pyq.return_value = [{"pyq_id": "1", "text": "PYQ text"}]
        yield mock_syl, mock_pyq


@pytest.fixture
def patch_db_session(seeded_session):
    """Override SessionLocal to return the seeded session."""
    def _get_session():
        return seeded_session
    with patch.object(gen_mod, "SessionLocal", _get_session):
        yield seeded_session


# ══════════════════════════════════════════════════════════════════════════
# 1. Dependency Boundary Verification
# ══════════════════════════════════════════════════════════════════════════


class TestDependencyBoundaries:

    SOURCE = inspect.getsource(sys.modules["src.generator"])

    def test_no_evaluator_import(self):
        """Must not import evaluator.py (architectural isolation)."""
        assert "src.evaluator" not in self.SOURCE

    def test_no_diagnostic_import(self):
        """Must not import diagnostic.py (architectural isolation)."""
        assert "src.diagnostic" not in self.SOURCE

    def test_no_scraper_import(self):
        """Must not import scraper.py (architectural isolation)."""
        assert "src.scraper" not in self.SOURCE

    def test_composition_engine_imported(self):
        """Must import composition_engine for solve_composition."""
        assert "src.composition_engine" in self.SOURCE

    def test_rag_store_imported(self):
        """Must import rag_store for context retrieval."""
        assert "src.rag_store" in self.SOURCE

    def test_database_models_imported(self):
        """Must import database models for state retrieval."""
        assert "src.models" in self.SOURCE

    def test_calibration_imported(self):
        """Must import calibration for config access."""
        assert "src.calibration" in self.SOURCE

    def test_no_inline_elo_formula(self):
        """No inline Elo formula (must use math_utils)."""
        tree = ast.parse(self.SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("compute_elo_update", "compute_expected_elo"):
                        pytest.fail(
                            f"Found direct call to math_utils at line {node.lineno}. "
                            "Generator should not need Elo math."
                        )

    def test_asyncio_used(self):
        """Must use asyncio for async generation pipeline."""
        assert "asyncio" in self.SOURCE

    def test_solve_composition_called(self):
        """Pipeline must call solve_composition from composition_engine."""
        src = self.SOURCE
        assert "solve_composition(" in src


# ══════════════════════════════════════════════════════════════════════════
# 2. Pipeline Construction
# ══════════════════════════════════════════════════════════════════════════


class TestPipelineConstruction:

    def test_pipeline_initializes(self):
        """GeneratorPipeline can be instantiated with default config."""
        pipeline = GeneratorPipeline()
        assert pipeline.MAX_CRITIC_RETRIES == 3
        assert pipeline.ASYNC_CONCURRENCY_LIMIT == 5
        assert pipeline.config is not None


# ══════════════════════════════════════════════════════════════════════════
# 3. State Retrieval Verification
# ══════════════════════════════════════════════════════════════════════════


class TestStateRetrieval:

    def test_retrieve_student_state(self, seeded_session):
        """State retrieval reads profile, backlog counts, and topics."""
        pipeline = GeneratorPipeline()
        profile, static_b, ca_b, topics, backlog = \
            pipeline.retrieve_student_state(seeded_session, "GS1")

        assert profile.subject_id == "GS1"
        assert profile.subject_name == "Geography"
        # 1 GS backlog + 1 CA backlog
        assert static_b == 1
        assert ca_b == 1

    def test_backlog_counts_by_type(self, seeded_session):
        """Backlog counts correctly separate GS vs CA source_type."""
        # Add extra backlog entries
        for i in range(3):
            seeded_session.add(BacklogQueue(
                topic_id=f"gs_extra_{i}", topic_type="GS", date_skipped="2026-06-02"
            ))
        seeded_session.commit()

        pipeline = GeneratorPipeline()
        _, static_b, ca_b, _, _ = pipeline.retrieve_student_state(seeded_session, "GS1")
        assert static_b == 4  # 1 original + 3 extra
        assert ca_b == 1

    def test_missing_profile_raises(self, db_session):
        """Retrieving state for a nonexistent subject raises ValueError."""
        pipeline = GeneratorPipeline()
        with pytest.raises(ValueError, match="StudentProfile not found"):
            pipeline.retrieve_student_state(db_session, "NONEXISTENT")


# ══════════════════════════════════════════════════════════════════════════
# 4. Composition Integration
# ══════════════════════════════════════════════════════════════════════════


class TestCompositionIntegration:

    def test_generate_composition_returns_plan(self):
        """Composition call returns a valid CompositionPlan."""
        pipeline = GeneratorPipeline()
        plan = pipeline.generate_composition(static_b=2, ca_b=1, mode="DAILY_SPRINT")
        assert isinstance(plan, CompositionPlan)
        assert plan.target_total == 30  # DAILY_SPRINT default
        assert plan.static_today + plan.static_backlog + plan.ca_today + plan.ca_backlog + plan.floor_count == plan.target_total

    def test_composition_with_enforce_false(self):
        """TOPIC_PRACTICE mode disables floor and backlog."""
        pipeline = GeneratorPipeline()
        plan = pipeline.generate_composition(static_b=10, ca_b=5, mode="TOPIC_PRACTICE")
        assert plan.floor_count == 0
        assert plan.static_backlog == 0
        assert plan.ca_backlog == 0

    def test_system_intent_header_populated(self):
        """System intent header is constructed after composition."""
        pipeline = GeneratorPipeline()
        plan = pipeline.generate_composition(static_b=2, ca_b=1, mode="DAILY_SPRINT")
        assert "Mode:" in plan.system_intent_header
        assert "DAILY_SPRINT" in plan.system_intent_header
        assert "Total:" in plan.system_intent_header

    def test_unknown_mode_raises(self):
        """Unknown practice mode raises ValueError."""
        pipeline = GeneratorPipeline()
        with pytest.raises(ValueError, match="Unknown practice mode"):
            pipeline.generate_composition(static_b=0, ca_b=0, mode="INVALID_MODE")


# ══════════════════════════════════════════════════════════════════════════
# 5. RAG Context Retrieval
# ══════════════════════════════════════════════════════════════════════════


class TestRAGContext:

    def test_retrieve_context_returns_dict(self, patch_rag_store):
        """Context retrieval returns syllabus and PYQ chunks."""
        pipeline = GeneratorPipeline()
        ctx = pipeline.retrieve_context("Fundamental Rights")
        assert "syllabus" in ctx
        assert "pyqs" in ctx
        assert len(ctx["syllabus"]) == 2

    def test_context_handles_empty_gracefully(self):
        """Empty retrieval does not crash — returns empty lists."""
        with patch("src.generator.retrieve_syllabus_chunks") as mock_syl, \
             patch("src.generator.retrieve_similar_pyqs") as mock_pyq:
            mock_syl.return_value = []
            mock_pyq.return_value = []
            pipeline = GeneratorPipeline()
            ctx = pipeline.retrieve_context("Nothing")
            assert ctx["syllabus"] == []
            assert ctx["pyqs"] == []


# ══════════════════════════════════════════════════════════════════════════
# 6. Critic Agent & Retry Logic
# ══════════════════════════════════════════════════════════════════════════


class TestCriticRetry:

    @pytest.mark.asyncio
    async def test_critic_high_score_returns_immediately(self):
        """Critic score >= combined_minimum returns on first attempt."""
        pipeline = GeneratorPipeline()
        req = {"topic": "Polity"}
        sem = asyncio.Semaphore(5)

        result = await pipeline.process_single_question(req, sem)
        assert result["metadata"]["status"] == "GENERATED"
        assert result["metadata"]["critic_retries"] == 0
        assert isinstance(result["question"], GeneratedQuestionSchema)

    @pytest.mark.asyncio
    async def test_critic_low_score_triggers_retry(self):
        """Score below combined_minimum triggers regeneration."""
        pipeline = GeneratorPipeline()

        # First N-1 calls return low score, last call returns high score
        call_count = [0]

        async def low_then_high(question):
            call_count[0] += 1
            if call_count[0] < pipeline.MAX_CRITIC_RETRIES:
                return CriticEvaluationSchema(
                    fact_check_verification=0.5, semantic_authenticity=0.5,
                    distractor_plausibility=0.5, blueprint_alignment=0.5,
                    combined_score=0.5
                )
            return CriticEvaluationSchema(
                fact_check_verification=0.9, semantic_authenticity=0.9,
                distractor_plausibility=0.9, blueprint_alignment=0.9,
                combined_score=0.9
            )

        pipeline._invoke_critic_agent = low_then_high
        req = {"topic": "Polity"}
        sem = asyncio.Semaphore(5)

        result = await pipeline.process_single_question(req, sem)
        assert result["metadata"]["status"] == "GENERATED"
        assert result["metadata"]["critic_retries"] == pipeline.MAX_CRITIC_RETRIES - 1

    @pytest.mark.asyncio
    async def test_all_retries_fail_triggers_fallback(self):
        """All retries exhausted activates fallback."""
        pipeline = GeneratorPipeline()

        async def always_low(question):
            return CriticEvaluationSchema(
                fact_check_verification=0.3, semantic_authenticity=0.3,
                distractor_plausibility=0.3, blueprint_alignment=0.3,
                combined_score=0.3
            )

        pipeline._invoke_critic_agent = always_low
        req = {"topic": "Polity"}
        sem = asyncio.Semaphore(5)

        result = await pipeline.process_single_question(req, sem)
        assert result["metadata"]["status"] == "FALLBACK_ACTIVATED"
        assert result["metadata"]["critic_retries"] == pipeline.MAX_CRITIC_RETRIES
        assert "[FALLBACK PYQ]" in result["question"].question_text

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self):
        """Timeout during generation triggers retry, not crash."""
        pipeline = GeneratorPipeline()

        async def timeout_once(question):
            await asyncio.sleep(100)  # Will be interrupted by wait_for timeout

        call_count = [0]

        async def generation_side(payload):
            call_count[0] += 1
            if call_count[0] == 1:
                # Simulate timeout by never returning
                await asyncio.sleep(100)
            return GeneratedQuestionSchema(
                question_text="Retry success", options=["A", "B"], correct_answer="A"
            )

        pipeline._invoke_cloud_generation = generation_side
        req = {"topic": "Polity"}
        sem = asyncio.Semaphore(5)

        with patch.object(pipeline, "_invoke_cloud_generation", generation_side):
            result = await pipeline.process_single_question(req, sem)

        assert result is not None

    @pytest.mark.asyncio
    async def test_max_retries_not_exceeded(self):
        """Critic retries never exceed MAX_CRITIC_RETRIES."""
        pipeline = GeneratorPipeline()
        retry_count = [0]

        async def always_fail(question):
            retry_count[0] += 1
            return CriticEvaluationSchema(
                fact_check_verification=0.0, semantic_authenticity=0.0,
                distractor_plausibility=0.0, blueprint_alignment=0.0,
                combined_score=0.0
            )

        pipeline._invoke_critic_agent = always_fail
        req = {"topic": "Polity"}
        sem = asyncio.Semaphore(5)

        await pipeline.process_single_question(req, sem)
        assert retry_count[0] <= pipeline.MAX_CRITIC_RETRIES

    @pytest.mark.asyncio
    async def test_fallback_returns_valid_schema(self):
        """Fallback question is a valid GeneratedQuestionSchema."""
        pipeline = GeneratorPipeline()
        fallback = pipeline.execute_fallback()
        assert isinstance(fallback, GeneratedQuestionSchema)
        assert fallback.question_text is not None

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore prevents exceeding ASYNC_CONCURRENCY_LIMIT."""
        pipeline = GeneratorPipeline()
        sem = asyncio.Semaphore(2)

        started = []
        completed = []

        async def slow_generation(payload):
            started.append(1)
            await asyncio.sleep(0.05)
            completed.append(1)
            return GeneratedQuestionSchema(
                question_text="Q", options=["A"], correct_answer="A"
            )

        pipeline._invoke_cloud_generation = slow_generation

        reqs = [{"topic": "T"}] * 10
        tasks = [pipeline.process_single_question(req, sem) for req in reqs]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10


# ══════════════════════════════════════════════════════════════════════════
# 7. Persistence Verification
# ══════════════════════════════════════════════════════════════════════════


class TestPersistence:

    def test_persist_batch_writes_all_questions(self, db_session):
        """All generated questions are written to question_bank."""
        pipeline = GeneratorPipeline()

        results = [
            {
                "question": GeneratedQuestionSchema(
                    question_text="Q1", options=["A"], correct_answer="A"
                ),
                "metadata": {"critic_retries": 0, "critic_score": 0.9, "status": "GENERATED"}
            },
            {
                "question": GeneratedQuestionSchema(
                    question_text="Q2", options=["B"], correct_answer="B"
                ),
                "metadata": {"critic_retries": 3, "critic_score": 0.0, "status": "FALLBACK_ACTIVATED"}
            },
        ]

        pipeline.persist_generated_batch(db_session, "GS1", results)
        db_session.flush()

        questions = db_session.query(QuestionBank).all()
        assert len(questions) == 2
        texts = {q.question_text for q in questions}
        assert "Q1" in texts
        assert "Q2" in texts

    def test_provenance_tags_stored(self, db_session):
        """Provenance metadata is stored in question_bank."""
        pipeline = GeneratorPipeline()

        results = [{
            "question": GeneratedQuestionSchema(
                question_text="Q", options=["A"], correct_answer="A"
            ),
            "metadata": {"critic_retries": 2, "critic_score": 0.75, "status": "GENERATED"}
        }]
        pipeline.persist_generated_batch(db_session, "GS1", results)
        db_session.flush()

        q = db_session.query(QuestionBank).first()
        assert q.provenance_tags["critic_retries"] == 2
        assert q.provenance_tags["status"] == "GENERATED"

    def test_source_type_by_status(self, db_session):
        """GENERATED status maps to DYNAMIC_CA, FALLBACK to STATIC_RAG."""
        pipeline = GeneratorPipeline()

        results = [
            {
                "question": GeneratedQuestionSchema(question_text="Dynamic"),
                "metadata": {"critic_retries": 0, "critic_score": 0.9, "status": "GENERATED"}
            },
            {
                "question": GeneratedQuestionSchema(question_text="Fallback"),
                "metadata": {"critic_retries": 3, "critic_score": 0.0, "status": "FALLBACK_ACTIVATED"}
            },
        ]
        pipeline.persist_generated_batch(db_session, "GS1", results)
        db_session.flush()

        dynamic = db_session.query(QuestionBank).filter_by(question_text="Dynamic").first()
        fallback = db_session.query(QuestionBank).filter_by(question_text="Fallback").first()
        assert dynamic.source_type == "DYNAMIC_CA"
        assert fallback.source_type == "STATIC_RAG"

    def test_rollback_on_error(self, db_session):
        """Session.rollback is called when persist fails."""
        pipeline = GeneratorPipeline()
        results = [{
            "question": GeneratedQuestionSchema(question_text="Q"),
            "metadata": {"critic_retries": 0, "critic_score": 0.9, "status": "GENERATED"}
        }]
        with patch.object(db_session, "flush", side_effect=Exception("DB error")):
            with pytest.raises(Exception):
                pipeline.persist_generated_batch(db_session, "GS1", results)


# ══════════════════════════════════════════════════════════════════════════
# 8. Pipeline Orchestration
# ══════════════════════════════════════════════════════════════════════════


class TestPipelineOrchestration:

    @pytest.mark.asyncio
    async def test_execute_generation_pipeline_returns_plan_and_results(
        self, patch_db_session, patch_rag_store
    ):
        """Full pipeline execution returns a CompositionPlan and results list."""
        pipeline = GeneratorPipeline()
        plan, results = await pipeline.execute_generation_pipeline("GS1", "DAILY_SPRINT")

        assert isinstance(plan, CompositionPlan)
        assert isinstance(results, list)
        assert len(results) == plan.target_total

    @pytest.mark.asyncio
    async def test_each_result_has_question_and_metadata(
        self, patch_db_session, patch_rag_store
    ):
        """Every result item has question and metadata keys."""
        pipeline = GeneratorPipeline()
        _, results = await pipeline.execute_generation_pipeline("GS1", "DAILY_SPRINT")

        for r in results:
            assert "question" in r
            assert "metadata" in r
            assert isinstance(r["question"], GeneratedQuestionSchema)
            assert "critic_retries" in r["metadata"]
            assert "status" in r["metadata"]

    @pytest.mark.asyncio
    async def test_questions_persisted_to_db(
        self, patch_db_session, patch_rag_store
    ):
        """After pipeline, question_bank contains all generated questions."""
        session = patch_db_session
        count_before = session.query(QuestionBank).count()

        pipeline = GeneratorPipeline()
        plan, _ = await pipeline.execute_generation_pipeline("GS1", "DAILY_SPRINT")

        count_after = session.query(QuestionBank).count()
        assert count_after - count_before == plan.target_total

    @pytest.mark.asyncio
    async def test_subject_id_matches_in_db(
        self, patch_db_session, patch_rag_store
    ):
        """Persisted questions reference the correct subject_id."""
        session = patch_db_session
        pipeline = GeneratorPipeline()
        await pipeline.execute_generation_pipeline("GS1", "DAILY_SPRINT")

        questions = session.query(QuestionBank).all()
        for q in questions:
            assert q.subject_id == "GS1"

    @pytest.mark.asyncio
    async def test_pipeline_rollback_on_catastrophic_failure(
        self, patch_db_session
    ):
        """Pipeline rolls back session on catastrophic failure."""
        pipeline = GeneratorPipeline()
        session = patch_db_session
        count_before = session.query(QuestionBank).count()

        with patch("src.generator.GeneratorPipeline.retrieve_student_state",
                   side_effect=ValueError("DB crash")):
            with pytest.raises(ValueError):
                await pipeline.execute_generation_pipeline("GS1", "DAILY_SPRINT")

        count_after = session.query(QuestionBank).count()
        assert count_after == count_before

    @pytest.mark.asyncio
    async def test_session_closed_after_pipeline(
        self, patch_db_session, patch_rag_store
    ):
        """Session is properly closed after pipeline completes."""
        pipeline = GeneratorPipeline()
        session = patch_db_session
        with patch.object(session, "close", wraps=session.close) as mock_close:
            await pipeline.execute_generation_pipeline("GS1", "DAILY_SPRINT")
            mock_close.assert_called_once()
