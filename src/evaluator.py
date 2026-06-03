import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, ValidationError

from src.database import SessionLocal
from src.models import QuestionBank, AttemptHistory
import src.calibration as calibration

logger = logging.getLogger(__name__)

# --- Schemas ---
class MainsEvaluationDetails(BaseModel):
    relevance_score: float
    coverage_score: float
    structure_score: float
    analysis_score: float
    evidence_score: float
    conclusion_score: float
    
class CriticVerificationSchema(BaseModel):
    semantic_alignment: float
    hallucination_detected: bool
    blueprint_adherence: float
    confidence_score: float


class EvaluationPipeline:
    """
    Phase 3 Group 3: The Evaluator Pipeline.
    Evaluates student answers based on rigorous UPSC metrics, handles both MCQ and Mains.
    Strictly independent of Generator and Composition math.
    """
    def __init__(self):
        self.config = calibration.get_config()
        self.mains_weights = self.config.evaluator.get("mains_weights", {
            "relevance": 0.25,
            "coverage": 0.20,
            "structure": 0.15,
            "analysis": 0.20,
            "evidence": 0.10,
            "conclusion": 0.10
        })
        
    # =========================================================================
    # Stage 1: Input Resolution
    # =========================================================================
    def resolve_input(self, session, question_id: str) -> QuestionBank:
        question = session.query(QuestionBank).filter_by(question_id=question_id).first()
        if not question:
            raise ValueError(f"Question {question_id} not found in QuestionBank.")
        if not question.metadata_json:
            raise ValueError(f"Question {question_id} missing blueprint/metadata.")
        return question

    # =========================================================================
    # Stage 2: Structural Evaluation
    # =========================================================================
    def structural_evaluate_mcq(self, question: QuestionBank, student_response: str) -> Dict[str, Any]:
        """Evaluates MCQs using deterministic correctness scoring."""
        correct_key = question.correct_key
        if correct_key is None:
            raise ValueError(f"MCQ Question {question.question_id} is missing a correct_key.")
            
        student_ans = str(student_response).strip().upper()
        # Simple extraction: assumes "A", "B", "C", "D" format for MCQ
        is_correct = (student_ans == str(correct_key).strip().upper())
        
        return {
            "type": "MCQ",
            "is_correct": is_correct,
            "raw_score": 1.0 if is_correct else 0.0,
            "distractor_validity": True,
            "answer_existence": True
        }

    async def structural_evaluate_mains(self, question: QuestionBank, student_response: str) -> Dict[str, Any]:
        """Mock LLM evaluation according to UPSC-style dimensions."""
        if not student_response or len(student_response.split()) < 10:
            raise ValueError("Malformed or critically short answer for Mains.")
            
        details = MainsEvaluationDetails(
            relevance_score=0.80,
            coverage_score=0.70,
            structure_score=0.90,
            analysis_score=0.85,
            evidence_score=0.75,
            conclusion_score=0.80
        )
        return {
            "type": "MAINS",
            "details": details.model_dump(),
            "raw_score": 0.0 # Will be populated in Stage 3
        }

    # =========================================================================
    # Stage 3: Weighting Rules
    # =========================================================================
    def apply_weighting_rules(self, eval_result: Dict[str, Any]) -> float:
        """Applies configuration-driven weights for Mains scoring."""
        if eval_result["type"] == "MCQ":
            return eval_result["raw_score"]
            
        if eval_result["type"] == "MAINS":
            details = eval_result["details"]
            score = (
                details["relevance_score"] * self.mains_weights.get("relevance", 0.25) +
                details["coverage_score"] * self.mains_weights.get("coverage", 0.20) +
                details["structure_score"] * self.mains_weights.get("structure", 0.15) +
                details["analysis_score"] * self.mains_weights.get("analysis", 0.20) +
                details["evidence_score"] * self.mains_weights.get("evidence", 0.10) +
                details["conclusion_score"] * self.mains_weights.get("conclusion", 0.10)
            )
            eval_result["raw_score"] = score
            return score
            
        return 0.0

    # =========================================================================
    # Stage 4: Critic / Adversarial Pass
    # =========================================================================
    async def run_critic_pass(self, question: QuestionBank, student_response: str, eval_result: Dict[str, Any]) -> CriticVerificationSchema:
        """Adversarial verification for hallucinations and semantic alignment."""
        # Simulated LLM critic checks
        return CriticVerificationSchema(
            semantic_alignment=0.95,
            hallucination_detected=False,
            blueprint_adherence=0.90,
            confidence_score=0.88
        )

    # =========================================================================
    # Stage 5: Score Normalization
    # =========================================================================
    def normalize_score(self, raw_score: float) -> float:
        """Deterministic bounding to [0.0, 1.0]."""
        return max(0.0, min(1.0, float(raw_score)))

    # =========================================================================
    # Stage 6: Persistence
    # =========================================================================
    def persist_evaluation(self, session, question: QuestionBank, session_id: str, student_response: str, 
                           normalized_score: float, eval_result: Dict[str, Any], critic: CriticVerificationSchema) -> AttemptHistory:
        
        attempt = AttemptHistory(
            attempt_id=str(uuid.uuid4()),
            question_id=question.question_id,
            session_id=session_id,
            student_response=student_response,
            confidence_level="HIGH" if critic.confidence_score >= 0.8 else ("MEDIUM" if critic.confidence_score >= 0.5 else "LOW"),
            response_duration_seconds=60.0,
            score_percentage=normalized_score,
            detailed_evaluation=str(eval_result),
            thinking_pattern_score=int(critic.semantic_alignment * 100),
            evaluation_time_ms=150,
            tokens_consumed=500,
            attempted_at=datetime.now(timezone.utc)
        )
        session.add(attempt)
        return attempt

    # =========================================================================
    # Orchestrator
    # =========================================================================
    async def evaluate_answer(self, question_id: str, session_id: str, student_response: str) -> Dict[str, Any]:
        """Main flow orchestrating Stages 1 through 7."""
        session = SessionLocal()
        try:
            # Stage 1: Input Resolution
            question = self.resolve_input(session, question_id)
            
            # Stage 2: Structural Evaluation
            if question.question_type == "MAINS_SUBJECTIVE":
                eval_result = await self.structural_evaluate_mains(question, student_response)
            else:
                eval_result = self.structural_evaluate_mcq(question, student_response)
                
            # Stage 3: Weighting Rules
            raw_score = self.apply_weighting_rules(eval_result)
            
            # Stage 4: Critic Pass
            critic_result = await self.run_critic_pass(question, student_response, eval_result)
            
            # Penalize hallucinations heavily if adversarial pass detects them
            if critic_result.hallucination_detected:
                raw_score *= 0.5
                
            # Stage 5: Normalization
            normalized_score = self.normalize_score(raw_score)
            
            # Stage 6: Persistence
            attempt = self.persist_evaluation(session, question, session_id, student_response, 
                                              normalized_score, eval_result, critic_result)
            
            session.commit()
            
            return {
                "attempt_id": attempt.attempt_id,
                "normalized_score": normalized_score,
                "raw_score": raw_score,
                "critic_verification": critic_result.model_dump()
            }
            
        except Exception as e:
            # Stage 7: Failure Handling
            session.rollback()
            logger.error(f"Evaluation Pipeline failed for {question_id}: {e}")
            raise
        finally:
            session.close()
