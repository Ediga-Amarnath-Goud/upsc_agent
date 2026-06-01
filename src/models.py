from datetime import datetime, timezone
import json
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, 
    ForeignKey, Text, DateTime, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def utcnow():
    return datetime.now(timezone.utc)

class StudentProfile(Base):
    __tablename__ = "student_profile"

    subject_id = Column(String, primary_key=True)
    subject_name = Column(String, nullable=False)
    current_elo_rating = Column(Integer, default=1200)
    baseline_elo_rating = Column(Integer, nullable=True)  # Set at diagnostic
    recovery_velocity_score = Column(Float, default=0.0)
    consecutive_stable_attempts = Column(Integer, default=0)
    total_questions_attempted = Column(Integer, default=0)
    weakness_tags = Column(JSON, default=list)  # Serialized JSON array
    last_reviewed_at = Column(DateTime, nullable=True)

    # Relationships
    topic_progress = relationship("TopicProgress", back_populates="student")
    daily_study_logs = relationship("DailyStudyLog", back_populates="student")
    questions = relationship("QuestionBank", back_populates="student")


class TopicProgress(Base):
    __tablename__ = "topic_progress"

    topic_id = Column(String, primary_key=True)
    subject_id = Column(String, ForeignKey("student_profile.subject_id"), nullable=False)
    topic_name = Column(String, nullable=False)
    base_stability_index = Column(Float, default=3.0)
    times_reviewed = Column(Integer, default=0)
    mistake_count = Column(Integer, default=0)
    last_reviewed_at = Column(DateTime, nullable=True)
    next_review_due = Column(DateTime, nullable=True)

    # Relationships
    student = relationship("StudentProfile", back_populates="topic_progress")


class DailyStudyLog(Base):
    __tablename__ = "daily_study_log"

    date_string = Column(String, primary_key=True)  # YYYY-MM-DD
    core_gs_topic = Column(String, ForeignKey("student_profile.subject_id"), nullable=True)
    csat_topic = Column(String, nullable=True)
    status = Column(String, default="PENDING")  # PENDING, COMPLETED, SKIPPED
    hours_logged = Column(Float, default=0.0)
    practice_mode = Column(String, nullable=True)  # A3
    study_context = Column(JSON, nullable=True)    # A6
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    student = relationship("StudentProfile", back_populates="daily_study_logs")


class BacklogQueue(Base):
    __tablename__ = "backlog_queue"

    topic_id = Column(String, primary_key=True)
    topic_type = Column(String, nullable=False)  # GS or CSAT
    date_skipped = Column(String, nullable=False)  # YYYY-MM-DD
    priority_weight = Column(Integer, default=1)
    times_tested_in_backlog = Column(Integer, default=0)
    source_type = Column(String, nullable=True)  # C-09


class CurrentAffairsFeed(Base):
    __tablename__ = "current_affairs_feed"

    article_id = Column(String, primary_key=True)
    source = Column(String, nullable=False)
    title = Column(String, nullable=False)
    raw_content = Column(Text, nullable=False)
    syllabus_mapping = Column(String, nullable=True)
    ai_synthesis = Column(Text, nullable=True)
    fetched_at = Column(DateTime, default=utcnow)
    test_generated_flag = Column(Boolean, default=False)


class QuestionBank(Base):
    __tablename__ = "question_bank"

    question_id = Column(String, primary_key=True)
    subject_id = Column(String, ForeignKey("student_profile.subject_id"), nullable=False)
    source_type = Column(String, nullable=False)  # STATIC_RAG, DYNAMIC_CA, INTEGRATED
    question_type = Column(String, nullable=False)  # PRELIMS_GS, CSAT, MAINS_SUBJECTIVE
    difficulty_level = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=False)  # GeneratedQuestionSchema payload
    correct_key = Column(String, nullable=True)   # Null for Mains
    provenance_tags = Column(JSON, nullable=False)
    generation_time_ms = Column(Integer, nullable=True)
    tokens_consumed = Column(Integer, nullable=True)
    critic_retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    student = relationship("StudentProfile", back_populates="questions")
    attempts = relationship("AttemptHistory", back_populates="question")


class AttemptHistory(Base):
    __tablename__ = "attempt_history"

    attempt_id = Column(String, primary_key=True)
    question_id = Column(String, ForeignKey("question_bank.question_id"), nullable=False)
    session_id = Column(String, nullable=False)
    student_response = Column(Text, nullable=False)
    confidence_level = Column(String, nullable=True)  # HIGH, MEDIUM, LOW
    response_duration_seconds = Column(Float, nullable=True)
    score_percentage = Column(Float, nullable=False)
    detailed_evaluation = Column(Text, nullable=True)
    thinking_pattern_score = Column(Integer, nullable=True)
    evaluation_time_ms = Column(Integer, nullable=True)
    tokens_consumed = Column(Integer, nullable=True)
    attempted_at = Column(DateTime, default=utcnow)

    # Relationships
    question = relationship("QuestionBank", back_populates="attempts")


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    experiment_id = Column(String, primary_key=True)
    config_version = Column(String, nullable=False)
    benchmark_score = Column(Float, nullable=False)
    run_date = Column(DateTime, default=utcnow)
    engineering_notes = Column(Text, nullable=True)


class ManualOverride(Base):
    __tablename__ = "manual_overrides"

    override_id = Column(String, primary_key=True)
    target_id = Column(String, nullable=False)
    override_type = Column(String, nullable=False)  # EVALUATION_DISPUTE, QUESTION_REJECTED, TOPIC_FORCED
    user_correction_notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=utcnow)


class TestSession(Base):
    __tablename__ = "test_sessions"

    session_id = Column(String, primary_key=True)  # UUID
    student_id = Column(String, default="default") # Single-user V1
    subject_code = Column(String, nullable=False)  # R3 rename
    test_type = Column(String, nullable=False)     # PRELIMS_GS, CSAT, MAINS_SUBJECTIVE
    practice_mode = Column(String, default="DAILY_SPRINT")
    study_context = Column(JSON, nullable=True)
    topics_requested = Column(JSON, nullable=True)
    question_count = Column(Integer, default=30)
    composition_summary = Column(Text, nullable=True)
    session_started_at = Column(DateTime, default=utcnow)
    last_activity_at = Column(DateTime, default=utcnow)
    session_status = Column(String, default="ACTIVE") # ACTIVE, COMPLETED, EXPIRED
