from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ─── API Boundaries (Internal & External) ───

class TestRequestSchema(BaseModel):
    """Payload for requesting a new test session (A1, A3, A6)."""
    model_config = ConfigDict(extra="forbid")

    subject_code: str = Field(..., description="The subject identifier, e.g., POLITY")
    test_type: Literal["PRELIMS_GS", "CSAT", "MAINS_SUBJECTIVE"] = Field(..., description="Test format: PRELIMS_GS, CSAT, or MAINS_SUBJECTIVE")
    mode: Literal["DAILY_SPRINT", "TOPIC_PRACTICE", "REVISION_MODE", "MOCK_TEST"] = Field("DAILY_SPRINT", description="Practice mode controlling composition constraints")
    topics: list[str] | None = Field(None, description="Optional list of specific topics to constrain generation")
    question_count: int | None = Field(None, description="Override default question count for the mode")
    study_context: dict[str, str] | None = Field(None, description="Key-value pairs for soft weighting (e.g., {'today_focus': 'POLITY'})")


class SubmitAnswerResponseSchema(BaseModel):
    """Response payload when a user submits an answer (Q3)."""
    model_config = ConfigDict(extra="forbid")

    score: float = Field(..., description="The score awarded for the response")
    elo_delta: int = Field(..., description="The change in Elo rating after this submission")
    psychological_drift_warning: bool = Field(..., description="True if pacing or behavior variance flags drift")
    warning_reason: str | None = Field(None, description="Human-readable reason for the drift warning")


# ─── LLM Structured Outputs ───

class PrelimsOptionSchema(BaseModel):
    """Represents a single option in a multiple-choice question."""
    model_config = ConfigDict(extra="forbid")

    id: Literal["A", "B", "C", "D"] = Field(..., description="Option identifier (A, B, C, D)")
    text: str = Field(..., description="The text of the option")


class ExplanationSchema(BaseModel):
    """Explanation of the correct answer and why other options are incorrect."""
    model_config = ConfigDict(extra="forbid")

    simple_core_concept: str = Field(..., description="The core principle being tested")
    step_by_step_justification: str = Field(..., description="Detailed justification of the correct option")
    correct_logic: str = Field(..., description="Why the correct answer is right")
    incorrect_logic: dict[str, str] = Field(..., description="Mapping of incorrect option IDs to explanations of why they are wrong")


class TrapAnalysisSchema(BaseModel):
    """Metadata regarding the cognitive traps embedded in the question."""
    model_config = ConfigDict(extra="forbid")

    trap_type: str = Field(..., description="The main cognitive trap (e.g., Extreme Phrasing, Semantic Drift)")
    trap_mechanism: str = Field(..., description="Explicitly state how an unprepared student will be misled")
    elimination_clue: str = Field(..., description="Clue used to eliminate this trap")


class GeneratedQuestionSchema(BaseModel):
    """Complete schema for an AI-generated Prelims question."""
    model_config = ConfigDict(extra="forbid")

    question_text: str = Field(..., description="The stem of the question")
    options: list[PrelimsOptionSchema] = Field(..., min_length=4, max_length=4, description="List of Exactly 4 options")
    correct_option_id: Literal["A", "B", "C", "D"] = Field(..., description="The ID of the correct option (A, B, C, or D)")
    difficulty_tier: int = Field(..., ge=1, le=10, description="Difficulty tier from 1 to 10")
    explanation_data: ExplanationSchema = Field(..., description="Detailed explanation of the answer")
    trap_data: TrapAnalysisSchema = Field(..., description="Analysis of the traps embedded in the question")


class CriticEvaluationSchema(BaseModel):
    """Output from the Critic Agent validating a drafted question."""
    model_config = ConfigDict(extra="forbid")

    fact_check_verification: float = Field(..., ge=0.0, le=1.0, description="Score 0.0-1.0 for factual accuracy")
    semantic_authenticity: float = Field(..., ge=0.0, le=1.0, description="Score 0.0-1.0 for UPSC-style complexity")
    distractor_plausibility: float = Field(..., ge=0.0, le=1.0, description="Score 0.0-1.0 for distractor plausibility")
    blueprint_alignment: float = Field(..., ge=0.0, le=1.0, description="Score 0.0-1.0 for structural alignment")
    combined_score: float = Field(..., ge=0.0, le=1.0, description="Overall weighted score 0.0-1.0")
    rejection_reason: str | None = Field(None, description="Reason for rejection if any score falls below minimum thresholds")


class SafeModePYQSchema(BaseModel):
    """Schema for parsing flat JSON PYQ files during safe mode fallback (Q1)."""
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(..., description="Unique ID for the PYQ")
    question_text: str = Field(..., description="The stem of the question")
    options: dict[str, str] = Field(..., description="Option dictionary, e.g., {'A': '...', 'B': '...'}")
    correct_key: Literal["A", "B", "C", "D"] = Field(..., description="Correct option key (A, B, C, D)")
    difficulty_tier: int = Field(..., ge=1, le=10, description="Difficulty tier from 1 to 10")
    subject_id: str = Field(..., description="Subject identifier for fallback adaptive filtering")
    source_year: int = Field(..., description="Year the PYQ was asked")
