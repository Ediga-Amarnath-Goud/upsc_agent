import pytest
from pydantic import ValidationError
from src.schemas import (
    TestRequestSchema as _TestRequestSchema,
    SubmitAnswerResponseSchema,
    GeneratedQuestionSchema,
    CriticEvaluationSchema,
    SafeModePYQSchema,
    PrelimsOptionSchema,
    ExplanationSchema,
    TrapAnalysisSchema
)

def test_test_request_schema_valid():
    payload = {
        "subject_code": "POLITY",
        "test_type": "PRELIMS_GS",
        "mode": "TOPIC_PRACTICE",
        "topics": ["Parliament"],
        "question_count": 20,
        "study_context": {"today_focus": "POLITY"}
    }
    schema = _TestRequestSchema(**payload)
    assert schema.subject_code == "POLITY"

def test_test_request_schema_defaults():
    payload = {
        "subject_code": "ECONOMY",
        "test_type": "CSAT"
    }
    schema = _TestRequestSchema(**payload)
    assert schema.mode == "DAILY_SPRINT"

def test_test_request_schema_invalid():
    with pytest.raises(ValidationError):
        _TestRequestSchema(test_type="INVALID_TYPE", subject_code="POLITY")

def test_submit_answer_response_schema():
    payload = {
        "score": 0.75,
        "elo_delta": 15,
        "psychological_drift_warning": True,
        "warning_reason": "High pacing variance"
    }
    schema = SubmitAnswerResponseSchema(**payload)
    assert schema.elo_delta == 15

def test_safe_mode_pyq_schema():
    payload = {
        "question_id": "pyq_2023_1",
        "question_text": "What is the capital of France?",
        "options": {"A": "Berlin", "B": "Paris", "C": "Madrid", "D": "Rome"},
        "correct_key": "B",
        "difficulty_tier": 10,
        "subject_id": "GEOGRAPHY",
        "source_year": 2023
    }
    schema = SafeModePYQSchema(**payload)
    assert schema.subject_id == "GEOGRAPHY"

def test_safe_mode_pyq_schema_invalid_key():
    payload = {
        "question_id": "pyq", "question_text": "Q", "options": {}, "correct_key": "Z",
        "difficulty_tier": 5, "subject_id": "POLITY", "source_year": 2023
    }
    with pytest.raises(ValidationError):
        SafeModePYQSchema(**payload)

def test_generated_question_schema_bounds():
    payload = {
        "question_text": "Q",
        "options": [
            {"id": "A", "text": "Opt A"},
            {"id": "B", "text": "Opt B"},
            {"id": "C", "text": "Opt C"},
            {"id": "D", "text": "Opt D"}
        ],
        "correct_option_id": "A",
        "difficulty_tier": 11,
        "explanation_data": {
            "simple_core_concept": "Concept",
            "step_by_step_justification": "Step 1",
            "correct_logic": "Because",
            "incorrect_logic": {"B": "No"}
        },
        "trap_data": {
            "trap_type": "Semantic",
            "trap_mechanism": "Deceiving",
            "elimination_clue": "Read carefully"
        }
    }
    with pytest.raises(ValidationError):
        GeneratedQuestionSchema(**payload)

def test_schema_extra_forbid():
    payload = {
        "subject_code": "ECONOMY",
        "test_type": "CSAT",
        "hacked_field": "123"
    }
    with pytest.raises(ValidationError):
        _TestRequestSchema(**payload)

# --- NEW TESTS FOR COVERAGE GAPS ---

def test_critic_evaluation_schema_valid():
    payload = {
        "fact_check_verification": 0.9,
        "semantic_authenticity": 0.85,
        "distractor_plausibility": 0.8,
        "blueprint_alignment": 1.0,
        "combined_score": 0.88,
        "rejection_reason": None
    }
    schema = CriticEvaluationSchema(**payload)
    assert schema.combined_score == 0.88

def test_critic_evaluation_schema_invalid_bounds():
    payload = {
        "fact_check_verification": 1.5,  # Invalid: > 1.0
        "semantic_authenticity": 0.85,
        "distractor_plausibility": 0.8,
        "blueprint_alignment": 1.0,
        "combined_score": 0.88
    }
    with pytest.raises(ValidationError):
        CriticEvaluationSchema(**payload)

def test_prelims_option_schema_invalid_id():
    with pytest.raises(ValidationError):
        PrelimsOptionSchema(id="E", text="Invalid ID")

def test_trap_analysis_schema_valid():
    payload = {
        "trap_type": "Extreme Phrasing",
        "trap_mechanism": "Uses 'always'",
        "elimination_clue": "Spot absolute words"
    }
    schema = TrapAnalysisSchema(**payload)
    assert schema.trap_type == "Extreme Phrasing"

def test_explanation_schema_valid():
    payload = {
        "simple_core_concept": "Core",
        "step_by_step_justification": "Step",
        "correct_logic": "Logic",
        "incorrect_logic": {"B": "Wrong"}
    }
    schema = ExplanationSchema(**payload)
    assert schema.simple_core_concept == "Core"

def test_generated_question_schema_invalid_options_length():
    payload = {
        "question_text": "Q",
        "options": [
            {"id": "A", "text": "Opt A"},
            {"id": "B", "text": "Opt B"}
        ],  # Only 2 options, requires exactly 4
        "correct_option_id": "A",
        "difficulty_tier": 5,
        "explanation_data": {
            "simple_core_concept": "Concept",
            "step_by_step_justification": "Step 1",
            "correct_logic": "Because",
            "incorrect_logic": {"B": "No"}
        },
        "trap_data": {
            "trap_type": "Semantic",
            "trap_mechanism": "Deceiving",
            "elimination_clue": "Read carefully"
        }
    }
    with pytest.raises(ValidationError):
        GeneratedQuestionSchema(**payload)
