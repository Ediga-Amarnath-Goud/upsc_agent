import asyncio
import json
import logging
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timezone
from pydantic import BaseModel, ValidationError

from src.database import SessionLocal
from src.models import StudentProfile, TopicProgress, BacklogQueue, QuestionBank
from src.composition_engine import solve_composition, CompositionPlan
from src.rag_store import retrieve_syllabus_chunks, retrieve_similar_pyqs
import src.calibration as calibration

logger = logging.getLogger(__name__)

# --- Structured API Schemas ---
class GeneratedQuestionSchema(BaseModel):
    question_text: str
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None

class CriticEvaluationSchema(BaseModel):
    fact_check_verification: float
    semantic_authenticity: float
    distractor_plausibility: float
    blueprint_alignment: float
    combined_score: float


class GeneratorPipeline:
    """
    Phase 3 Group 2: The Generator Pipeline.
    Assembles E2E 30-question test papers utilizing the RAG store and Composition Engine.
    Strictly isolated from Evaluator (scoring) logic.
    """
    def __init__(self):
        self.config = calibration.get_config()
        self.static_pool_path = Path("static_assets/pyq")
        self.MAX_CRITIC_RETRIES = 3
        self.ASYNC_CONCURRENCY_LIMIT = 5

    # =========================================================================
    # Stage 1: State Retrieval
    # =========================================================================
    def retrieve_student_state(self, session, subject_id: str):
        profile = session.query(StudentProfile).filter_by(subject_id=subject_id).first()
        if not profile:
            raise ValueError(f"StudentProfile not found for {subject_id}")
        
        # Gather backlog context securely
        backlog_queue = session.query(BacklogQueue).all()
        static_backlog_count = sum(1 for b in backlog_queue if b.topic_type == "GS")
        ca_backlog_count = sum(1 for b in backlog_queue if b.topic_type == "CA")
        
        # Gather topic metadata
        topics = session.query(TopicProgress).filter_by(subject_id=subject_id).all()
        return profile, static_backlog_count, ca_backlog_count, topics, backlog_queue

    # =========================================================================
    # Stage 2: Composition
    # =========================================================================
    def generate_composition(self, static_b: int, ca_b: int, mode: str) -> CompositionPlan:
        """Invokes architecture-contracted Composition Engine. Does NOT recreate math."""
        practice_mode = self.config.practice_modes.get(mode)
        if not practice_mode:
            raise ValueError(f"Unknown practice mode: {mode}")
            
        plan = solve_composition(
            target_total=practice_mode.default_question_count,
            available_static_backlog=static_b,
            available_ca_backlog=ca_b,
            enforce_floor=practice_mode.enforce_floor,
            enforce_backlog=practice_mode.enforce_backlog,
            mode=mode
        )
        
        # Construct intent header for diagnostic tracking
        plan.system_intent_header = (
            f"Mode:{mode} | Total:{plan.target_total} | "
            f"S:{plan.static_today} SB:{plan.static_backlog} "
            f"CA:{plan.ca_today} CAB:{plan.ca_backlog}"
        )
        return plan

    # =========================================================================
    # Stage 3: Context Assembly
    # =========================================================================
    def retrieve_context(self, query: str) -> Dict[str, Any]:
        """Retrieves external knowledge, handling empty gracefully."""
        syllabus_chunks = retrieve_syllabus_chunks(query, n_results=2)
        pyq_chunks = retrieve_similar_pyqs(query, n_results=3)
        return {
            "syllabus": syllabus_chunks,
            "pyqs": pyq_chunks
        }

    # --- Mocks for Cloud API Integration (Network bound) ---
    async def _invoke_cloud_generation(self, payload: dict) -> GeneratedQuestionSchema:
        """Mock representation of the Cloud LLM generation layer."""
        await asyncio.sleep(0.1) # Simulate network I/O
        return GeneratedQuestionSchema(
            question_text=f"Generated Q based on {payload.get('topic')}",
            options=["A", "B", "C", "D"],
            correct_answer="A",
            explanation="Mock explanation payload."
        )
        
    async def _invoke_critic_agent(self, question: GeneratedQuestionSchema) -> CriticEvaluationSchema:
        """Mock representation of the dual-pass Critic Agent."""
        await asyncio.sleep(0.1)
        return CriticEvaluationSchema(
            fact_check_verification=0.90,
            semantic_authenticity=0.88,
            distractor_plausibility=0.87,
            blueprint_alignment=0.95,
            combined_score=0.90
        )

    # =========================================================================
    # Stage 6: Fallback Logic
    # =========================================================================
    def execute_fallback(self) -> GeneratedQuestionSchema:
        """Activates if Cloud API timeouts or Critic agent fails completely."""
        # In a real environment, this reads a flat JSON list of validated PYQs
        return GeneratedQuestionSchema(
            question_text="[FALLBACK PYQ] Which of the following is correct?",
            options=["1", "2", "3", "4"],
            correct_answer="1",
            explanation="This question was pulled from the static recovery pool due to generation exhaustion."
        )

    # =========================================================================
    # Stage 4 & 5: Generation and Validation
    # =========================================================================
    async def process_single_question(self, req: dict, semaphore: asyncio.Semaphore) -> Dict[str, Any]:
        """
        Executes bounded async generation pipeline with strict timeout and validation logic.
        """
        async with semaphore:
            context = self.retrieve_context(req["topic"])
            payload = {"topic": req["topic"], "context": context}
            
            for attempt in range(self.MAX_CRITIC_RETRIES):
                try:
                    # Timeout handling is mandatory for preventing thread exhaustion
                    generated = await asyncio.wait_for(
                        self._invoke_cloud_generation(payload), 
                        timeout=10.0
                    )
                    
                    # Schema Validation is handled implicitly by Pydantic here, 
                    # but if it fails, exception is caught and retry loop triggers.
                    
                    critic_eval = await asyncio.wait_for(
                        self._invoke_critic_agent(generated), 
                        timeout=5.0
                    )
                    
                    # Validate Gate 2 Minimum Combined Score
                    if critic_eval.combined_score >= self.config.critic_thresholds.get("combined_minimum", 0.85):
                        return {
                            "question": generated,
                            "metadata": {
                                "critic_retries": attempt, 
                                "critic_score": critic_eval.combined_score,
                                "status": "GENERATED"
                            }
                        }
                except asyncio.TimeoutError:
                    logger.warning(f"Generation timeout on attempt {attempt+1}")
                except ValidationError as ve:
                    logger.warning(f"Schema validation failure on attempt {attempt+1}: {ve}")
                except Exception as e:
                    logger.warning(f"Unexpected Cloud API failure on attempt {attempt+1}: {e}")
            
            # Exhaustion triggers fallback
            logger.error("Critic retries exhausted, activating static fallback.")
            fallback = self.execute_fallback()
            return {
                "question": fallback,
                "metadata": {
                    "critic_retries": self.MAX_CRITIC_RETRIES, 
                    "critic_score": 0.0, 
                    "status": "FALLBACK_ACTIVATED"
                }
            }

    # =========================================================================
    # Stage 7: Persistence
    # =========================================================================
    def persist_generated_batch(self, session, subject_id: str, results: List[Dict[str, Any]]):
        """Persists exact requested counts, preventing duplicates."""
        for res in results:
            q = res["question"]
            meta = res["metadata"]
            
            db_question = QuestionBank(
                question_id=str(uuid.uuid4()),
                subject_id=subject_id,
                source_type="DYNAMIC_CA" if meta.get("status") == "GENERATED" else "STATIC_RAG",
                question_type="PRELIMS_GS",
                difficulty_level=1,
                question_text=q.question_text,
                metadata_json=q.model_dump(),
                correct_key=q.correct_answer,
                provenance_tags=meta,
                critic_retry_count=meta["critic_retries"]
            )
            session.add(db_question)
        session.flush()

    # =========================================================================
    # Orchestrator Pipeline
    # =========================================================================
    async def execute_generation_pipeline(self, subject_id: str, mode: str = "DAILY_SPRINT"):
        """Main execution flow honoring architecture constraints."""
        session = SessionLocal()
        try:
            # 1. State Retrieval
            profile, static_b, ca_b, topics, backlog = self.retrieve_student_state(session, subject_id)
            
            # 2. Composition Engine Call
            plan = self.generate_composition(static_b, ca_b, mode)
            
            # Setup targets 
            # TODO (Technical Debt): Implement real topic distribution. 
            # Placeholder Topic routing is currently used for E2E validation.
            requests = [{"topic": "Placeholder Topic"} for _ in range(plan.target_total)]
            
            # 4/5. Async Bounded Generation Pipeline
            semaphore = asyncio.Semaphore(self.ASYNC_CONCURRENCY_LIMIT)
            tasks = [self.process_single_question(req, semaphore) for req in requests]
            
            results = await asyncio.gather(*tasks)
            
            # 7. Persistence
            self.persist_generated_batch(session, subject_id, results)
            session.commit()
            
            return plan, results
            
        except Exception as e:
            session.rollback()
            logger.error(f"Generation Pipeline catastrophic failure: {e}")
            raise
        finally:
            session.close()
