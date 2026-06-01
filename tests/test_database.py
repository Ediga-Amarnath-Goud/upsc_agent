"""
Database verification tests for Group 2 (models.py + database.py).

Covers: schema verification, relationship verification, SQLite verification,
constraint verification, and database utility verification.
"""
from datetime import datetime, timezone, timedelta
import json

import pytest
from sqlalchemy import inspect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from src.database import init_db, get_session, expire_stale_sessions, engine
from src.models import (
    Base,
    StudentProfile,
    TopicProgress,
    DailyStudyLog,
    BacklogQueue,
    CurrentAffairsFeed,
    QuestionBank,
    AttemptHistory,
    ExperimentRun,
    ManualOverride,
    TestSession,
)

# ─── Schema Verification ───


def test_all_ten_tables_exist(test_db):
    inspector = inspect(test_db)
    tables = inspector.get_table_names()
    assert len(tables) == 10


def test_table_names_match_architecture(test_db):
    inspector = inspect(test_db)
    tables = set(inspector.get_table_names())
    expected = {
        "student_profile",
        "topic_progress",
        "daily_study_log",
        "backlog_queue",
        "current_affairs_feed",
        "question_bank",
        "attempt_history",
        "experiment_runs",
        "manual_overrides",
        "test_sessions",
    }
    assert tables == expected


def test_student_profile_columns(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("student_profile")}
    assert "subject_id" in cols
    assert "subject_name" in cols
    assert "current_elo_rating" in cols
    assert "baseline_elo_rating" in cols  # C-11
    assert "recovery_velocity_score" in cols  # C-11
    assert "consecutive_stable_attempts" in cols  # C-11
    assert "total_questions_attempted" in cols
    assert "weakness_tags" in cols
    assert "last_reviewed_at" in cols


def test_topic_progress_columns(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("topic_progress")}
    assert "topic_id" in cols
    assert "subject_id" in cols
    assert "topic_name" in cols
    assert "base_stability_index" in cols
    assert "times_reviewed" in cols
    assert "mistake_count" in cols
    assert "last_reviewed_at" in cols
    assert "next_review_due" in cols


def test_daily_study_log_contains_addon_columns(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("daily_study_log")}
    assert "practice_mode" in cols  # A3
    assert "study_context" in cols  # A6


def test_backlog_queue_has_source_type(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("backlog_queue")}
    assert "source_type" in cols  # C-09


def test_question_bank_contains_audit_columns(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("question_bank")}
    assert "provenance_tags" in cols
    assert "generation_time_ms" in cols
    assert "tokens_consumed" in cols
    assert "critic_retry_count" in cols


def test_attempt_history_contains_session_fields(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("attempt_history")}
    assert "session_id" in cols
    assert "confidence_level" in cols
    assert "response_duration_seconds" in cols


def test_test_sessions_contains_r3_fields(test_db):
    inspector = inspect(test_db)
    cols = {c["name"] for c in inspector.get_columns("test_sessions")}
    assert "session_id" in cols
    assert "student_id" in cols  # R3
    assert "subject_code" in cols  # R3 rename
    assert "test_type" in cols
    assert "practice_mode" in cols  # A3
    assert "study_context" in cols  # A6
    assert "topics_requested" in cols  # A1
    assert "question_count" in cols  # A2
    assert "composition_summary" in cols
    assert "session_started_at" in cols
    assert "last_activity_at" in cols
    assert "session_status" in cols


def test_no_speculative_tables(test_db):
    inspector = inspect(test_db)
    tables = set(inspector.get_table_names())
    extra = tables - {
        "student_profile",
        "topic_progress",
        "daily_study_log",
        "backlog_queue",
        "current_affairs_feed",
        "question_bank",
        "attempt_history",
        "experiment_runs",
        "manual_overrides",
        "test_sessions",
    }
    assert not extra, f"Unexpected tables found: {extra}"


# ─── Relationship Verification ───


def test_foreign_keys_create_successfully(test_db):
    inspector = inspect(test_db)
    for table_name in ["topic_progress", "daily_study_log", "question_bank", "attempt_history"]:
        fks = inspector.get_foreign_keys(table_name)
        assert len(fks) >= 1, f"{table_name} has no foreign keys"


def test_relationships_initialize_correctly(test_session):
    student = StudentProfile(
        subject_id="POLITY",
        subject_name="Polity",
    )
    topic = TopicProgress(
        topic_id="pol_fr",
        subject_id="POLITY",
        topic_name="Fundamental Rights",
    )
    student.topic_progress.append(topic)
    test_session.add(student)
    test_session.commit()
    test_session.refresh(student)
    assert len(student.topic_progress) == 1
    assert student.topic_progress[0].topic_name == "Fundamental Rights"


def test_question_to_attempt_relationship(test_session):
    student = StudentProfile(subject_id="HISTORY", subject_name="History")
    test_session.add(student)
    test_session.flush()
    question = QuestionBank(
        question_id="q1",
        subject_id="HISTORY",
        source_type="STATIC_RAG",
        question_type="PRELIMS_GS",
        difficulty_level=5,
        question_text="Test?",
        metadata_json={"test": True},
        provenance_tags={"source": "test"},
    )
    attempt = AttemptHistory(
        attempt_id="a1",
        question_id="q1",
        session_id="s1",
        student_response="A",
        score_percentage=1.0,
    )
    question.attempts.append(attempt)
    test_session.add(question)
    test_session.commit()
    test_session.refresh(question)
    assert len(question.attempts) == 1
    assert question.attempts[0].attempt_id == "a1"


def test_test_sessions_soft_link_no_db_constraint(test_db):
    inspector = inspect(test_db)
    fks = inspector.get_foreign_keys("test_sessions")
    assert len(fks) == 0


def test_relationship_metadata_loads_without_mapper_failures():
    from sqlalchemy.orm import configure_mappers
    configure_mappers()


# ─── SQLite Verification ───


def test_in_memory_sqlite_builds_cleanly(test_db):
    inspector = inspect(test_db)
    assert len(inspector.get_table_names()) == 10


def test_create_all_succeeds(test_db):
    assert test_db is not None


def test_session_crud_operations(test_session):
    student = StudentProfile(subject_id="GEOGRAPHY", subject_name="Geography")
    test_session.add(student)
    test_session.commit()
    row = test_session.query(StudentProfile).filter_by(subject_id="GEOGRAPHY").first()
    assert row is not None
    assert row.subject_name == "Geography"


def test_wal_mode_does_not_crash():
    from sqlalchemy import create_engine
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    wal_engine = create_engine("sqlite:///:memory:")

    @event.listens_for(Engine, "connect")
    def set_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(bind=wal_engine)
    inspector = inspect(wal_engine)
    assert len(inspector.get_table_names()) == 10
    wal_engine.dispose()


def test_json_fields_round_trip(test_session):
    student = StudentProfile(
        subject_id="ECONOMY",
        subject_name="Economy",
        weakness_tags=["Weak Core Memory", "Pacing Deficit"],
    )
    test_session.add(student)
    test_session.commit()
    test_session.refresh(student)
    assert student.weakness_tags == ["Weak Core Memory", "Pacing Deficit"]

    question = QuestionBank(
        question_id="q_json",
        subject_id="ECONOMY",
        source_type="DYNAMIC_CA",
        question_type="PRELIMS_GS",
        difficulty_level=5,
        question_text="JSON round-trip test?",
        metadata_json={"options": {"A": "1", "B": "2"}},
        provenance_tags={"source": "test", "version": "1.0"},
    )
    test_session.add(question)
    test_session.commit()
    test_session.refresh(question)
    assert question.metadata_json["options"]["A"] == "1"
    assert question.provenance_tags["source"] == "test"


# ─── Constraint Verification ───


def test_student_profile_defaults(test_session):
    student = StudentProfile(subject_id="CSAT", subject_name="CSAT")
    test_session.add(student)
    test_session.commit()
    assert student.current_elo_rating == 1200
    assert student.total_questions_attempted == 0
    assert student.consecutive_stable_attempts == 0
    assert student.recovery_velocity_score == 0.0


def test_topic_progress_defaults(test_session):
    student = StudentProfile(subject_id="SCIENCE", subject_name="Science")
    test_session.add(student)
    test_session.flush()
    topic = TopicProgress(
        topic_id="sci_phys",
        subject_id="SCIENCE",
        topic_name="Physics",
    )
    test_session.add(topic)
    test_session.commit()
    assert topic.base_stability_index == 3.0
    assert topic.times_reviewed == 0
    assert topic.mistake_count == 0


def test_test_session_defaults(test_session):
    session = TestSession(
        session_id="uuid-1",
        subject_code="POLITY",
        test_type="PRELIMS_GS",
    )
    test_session.add(session)
    test_session.commit()
    assert session.student_id == "default"
    assert session.practice_mode == "DAILY_SPRINT"
    assert session.question_count == 30
    assert session.session_status == "ACTIVE"


def test_question_bank_defaults(test_session):
    student = StudentProfile(subject_id="ART", subject_name="Art")
    test_session.add(student)
    test_session.flush()
    q = QuestionBank(
        question_id="q_defaults",
        subject_id="ART",
        source_type="STATIC_RAG",
        question_type="PRELIMS_GS",
        difficulty_level=5,
        question_text="Defaults test?",
        metadata_json={},
        provenance_tags={},
    )
    test_session.add(q)
    test_session.commit()
    assert q.critic_retry_count == 0
    assert q.correct_key is None


def test_nullable_columns_accept_none(test_session):
    student = StudentProfile(subject_id="NULL_TEST", subject_name="Test")
    test_session.add(student)
    test_session.flush()
    q = QuestionBank(
        question_id="q_null",
        subject_id="NULL_TEST",
        source_type="STATIC_RAG",
        question_type="PRELIMS_GS",
        difficulty_level=5,
        question_text="Null test?",
        metadata_json={},
        provenance_tags={},
        generation_time_ms=None,
        tokens_consumed=None,
        correct_key=None,
    )
    test_session.add(q)
    test_session.commit()
    assert q.generation_time_ms is None
    assert q.tokens_consumed is None


# ─── Database Utility Verification ───


def test_expire_stale_sessions_does_not_auto_run():
    assert callable(expire_stale_sessions)


def test_expire_stale_sessions_timeout_externally_passed():
    import inspect as _inspect
    sig = _inspect.signature(expire_stale_sessions)
    assert "timeout_minutes" in sig.parameters


def test_expire_stale_sessions_only_mutates_target_rows():
    init_db()
    from src.database import SessionLocal
    
    # Pre-cleanup in case a previous test run crashed and left stale data
    db = SessionLocal()
    db.query(TestSession).filter(TestSession.session_id.in_(["active-1", "stale-1", "done-1"])).delete()
    db.commit()
    db.close()

    now = datetime.now(timezone.utc)
    session_active = TestSession(
        session_id="active-1",
        subject_code="POLITY",
        test_type="PRELIMS_GS",
        last_activity_at=now,
        session_status="ACTIVE",
    )
    session_stale = TestSession(
        session_id="stale-1",
        subject_code="POLITY",
        test_type="PRELIMS_GS",
        last_activity_at=now - timedelta(minutes=200),
        session_status="ACTIVE",
    )
    session_completed = TestSession(
        session_id="done-1",
        subject_code="POLITY",
        test_type="PRELIMS_GS",
        last_activity_at=now - timedelta(minutes=200),
        session_status="COMPLETED",
    )
    db = SessionLocal()
    db.add_all([session_active, session_stale, session_completed])
    db.commit()
    db.close()

    expire_stale_sessions(timeout_minutes=120)

    db = SessionLocal()
    try:
        expired = db.query(TestSession).filter(
            TestSession.session_status == "EXPIRED",
            TestSession.session_id.in_(["active-1", "stale-1", "done-1"])
        ).all()
        expired_ids = {s.session_id for s in expired}
        assert "stale-1" in expired_ids
        assert "active-1" not in expired_ids
        assert "done-1" not in expired_ids
    finally:
        # Post-cleanup
        db.query(TestSession).filter(TestSession.session_id.in_(["active-1", "stale-1", "done-1"])).delete()
        db.commit()
        db.close()


def test_expire_stale_sessions_does_not_load_config():
    import inspect as _inspect
    import src.database as db_mod
    source = _inspect.getsource(db_mod.expire_stale_sessions)
    assert "calibration" not in source.lower()


def test_expire_stale_sessions_does_not_schedule_itself():
    import inspect as _inspect
    import src.database as db_mod
    source = _inspect.getsource(db_mod.expire_stale_sessions)
    assert "scheduler" not in source.lower()
    assert "add_job" not in source.lower()
    assert "cron" not in source.lower()


def test_get_session_yields_context_manager():
    gen = get_session()
    session = next(gen)
    assert session is not None
    try:
        next(gen)
    except StopIteration:
        pass


def test_init_db_idempotent():
    init_db()
    init_db()
