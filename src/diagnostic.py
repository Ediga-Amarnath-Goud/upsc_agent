"""
Diagnostic Onboarding Module (Phase 2 Group 3)
Handles the student onboarding flow, partial state recovery, initialization of 
all required topics, and calibration of baseline Elo ratings.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.database import get_session
from src.models import StudentProfile, TopicProgress, TestSession
from src.calibration import get_config
import src.math_utils as math_utils

logger = logging.getLogger(__name__)

# Subject codes frozen in Phase 1
UPSC_SUBJECTS = {
    "GS1": "History, Art & Culture, Geography, Society",
    "GS2": "Polity, Governance, Social Justice, IR",
    "GS3": "Economy, Environment, S&T, Security",
    "GS4": "Ethics, Integrity, Aptitude",
    "CSAT": "Civil Services Aptitude Test"
}

# Baseline required topics to ensure downstream scheduling logic never crashes on None types
REQUIRED_TOPICS = {
    "GS1": ["Art and Culture", "Modern History", "Geography"],
    "GS2": ["Constitution", "Governance", "International Relations"],
    "GS3": ["Economy", "Environment", "Science and Tech"],
    "GS4": ["Ethics", "Integrity"],
    "CSAT": ["Math", "Logical Reasoning"]
}

def initialize_onboarding_session(student_id: str = "default") -> str:
    """
    Initializes the diagnostic session.
    Creates base subject profiles if they do not exist.
    Marks the session state as PARTIAL initially to protect downstream dependencies.
    """
    db = next(get_session())
    try:
        # Create student profile for each subject if not exists (Idempotent)
        for code, name in UPSC_SUBJECTS.items():
            profile = db.query(StudentProfile).filter_by(subject_id=code).first()
            if not profile:
                profile = StudentProfile(
                    subject_id=code,
                    subject_name=name,
                    current_elo_rating=get_config().elo_system.base_rating,
                )
                db.add(profile)
        
        session_id = str(uuid.uuid4())
        session = TestSession(
            session_id=session_id,
            student_id=student_id,
            subject_code="ALL",
            test_type="DIAGNOSTIC",
            practice_mode="ONBOARDING",
            session_status="PARTIAL"  # Explicit partial tracking
        )
        db.add(session)
        db.commit()
        logger.info(f"Initialized onboarding session: {session_id}")
        return session_id
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to initialize onboarding: {e}")
        raise
    finally:
        db.close()

def _initialize_all_topics(db):
    """
    Initializes topic_progress for ALL required topics with idempotent protection.
    This fulfills the architectural mandate to prevent missing scheduler state.
    """
    for subject_code, topics in REQUIRED_TOPICS.items():
        for topic_name in topics:
            topic_id = f"{subject_code}_{topic_name.replace(' ', '_').upper()}"
            existing = db.query(TopicProgress).filter_by(topic_id=topic_id).first()
            
            if not existing:
                progress = TopicProgress(
                    topic_id=topic_id,
                    subject_id=subject_code,
                    topic_name=topic_name,
                    base_stability_index=3.0,
                    times_reviewed=0,
                    mistake_count=0
                )
                db.add(progress)
    # Ensure they are committed before adjustments happen
    db.commit()

def process_diagnostic_results(session_id: str, results: List[Dict[str, Any]]):
    """
    Processes diagnostic results incrementally.
    Supports partial onboarding recovery by committing state row-by-row.
    """
    db = next(get_session())
    try:
        session = db.query(TestSession).filter_by(session_id=session_id).first()
        if not session:
            logger.error(f"Diagnostic session {session_id} not found.")
            return

        # 1. Initialize all topics identically to avoid null-pointer crashes
        _initialize_all_topics(db)
        
        config = get_config().diagnostic
        exceptional_threshold = config["exceptional_threshold"]
        average_threshold = config["average_threshold"]
        exceptional_elo = config["exceptional_elo"]
        average_elo = config["average_elo"]
        growth_elo = config["growth_elo"]
        
        # 2. Apply topic-level weakness adjustments incrementally
        for res in results:
            try:
                subject = res.get("subject")
                topic = res.get("topic")
                score = res.get("score", 0.0)
                
                if subject not in UPSC_SUBJECTS:
                    continue
                    
                topic_id = f"{subject}_{topic.replace(' ', '_').upper()}"
                topic_prog = db.query(TopicProgress).filter_by(topic_id=topic_id).first()
                profile = db.query(StudentProfile).filter_by(subject_id=subject).first()
                
                if topic_prog:
                    # Idempotency check to prevent penalty amplification on recovery reruns
                    if topic_prog.times_reviewed == 0:
                        if score < average_threshold:
                            # Apply weakness adjustments
                            topic_prog.mistake_count += 1
                            topic_prog.base_stability_index = max(1.0, topic_prog.base_stability_index - 0.5)
                            
                            # Persist weakness tag to student profile
                            if profile:
                                existing_tags = profile.weakness_tags or []
                                if topic not in existing_tags:
                                    # Create a new list to trigger SQLAlchemy JSON mutation detection
                                    profile.weakness_tags = list(set(existing_tags + [topic]))
                        
                        # Initialize review metadata
                        topic_prog.times_reviewed = 1
                        topic_prog.last_reviewed_at = datetime.now(timezone.utc)
                
                # Commit partial progress row-by-row for safe failure recovery
                db.commit()
            except Exception as loop_e:
                db.rollback()
                logger.error(f"Failed to process diagnostic result for {res}: {loop_e}")
                # Loop continues to ensure partial completion logic holds

        # 3. Calculate calibrated baseline Elo ratings using math_utils
        for subject in UPSC_SUBJECTS:
            subj_results = [r for r in results if r.get("subject") == subject]
            if not subj_results:
                continue
            
            avg_score = sum(r.get("score", 0.0) for r in subj_results) / len(subj_results)
            avg_diff = sum(r.get("difficulty", 5) for r in subj_results) / len(subj_results)
            
            profile = db.query(StudentProfile).filter_by(subject_id=subject).first()
            if profile:
                try:
                    # Leverage Phase 1 math utilities for dynamic base calculations
                    diff_elo = math_utils.compute_difficulty_to_elo(int(avg_diff))
                    
                    if avg_score >= exceptional_threshold:
                        profile.baseline_elo_rating = max(exceptional_elo, diff_elo)
                        profile.current_elo_rating = max(exceptional_elo, diff_elo)
                    elif avg_score >= average_threshold:
                        bounded_elo = min(exceptional_elo - 1, max(average_elo, diff_elo))
                        profile.baseline_elo_rating = bounded_elo
                        profile.current_elo_rating = bounded_elo
                    else:
                        bounded_elo = min(average_elo - 1, max(growth_elo, diff_elo))
                        profile.baseline_elo_rating = bounded_elo
                        profile.current_elo_rating = bounded_elo
                        
                    db.commit()
                except Exception as elo_e:
                    db.rollback()
                    logger.error(f"Failed to compute baseline Elo for {subject}: {elo_e}")
        
        # 4. Finalize state
        session.session_status = "COMPLETE"
        db.commit()
        logger.info(f"Diagnostic session {session_id} COMPLETED successfully.")
        
    except Exception as e:
        db.rollback()
        # Fallback to FAILED state if a critical outer-loop exception occurs
        try:
            session = db.query(TestSession).filter_by(session_id=session_id).first()
            if session:
                session.session_status = "FAILED"
                db.commit()
        except Exception as inner_e:
            db.rollback()
            logger.error(f"Failed to record FAILED diagnostic state: {inner_e}")
            
        logger.error(f"Diagnostic processing critically failed: {e}")
        # Partial progress via earlier loop commits is retained.
    finally:
        db.close()
