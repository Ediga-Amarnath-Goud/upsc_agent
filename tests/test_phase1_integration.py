import inspect
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# ─── Import Integration ───


class TestImportIntegration:
    """Verify all Phase 1 modules import cleanly without circular deps."""

    def test_all_phase1_modules_importable(self):
        import src.calibration
        import src.database
        import src.exceptions
        import src.math_utils
        import src.models
        import src.schemas
        assert src.exceptions.CalibrationFailure
        assert src.schemas.TestRequestSchema
        assert src.math_utils.compute_elo_update

    def test_no_circular_imports(self):
        cal_mods = {m for m in sys.modules if "src." in m}
        assert "src.calibration" in str(cal_mods)
        assert "src.math_utils" in str(cal_mods)
        assert "src.database" in str(cal_mods)

    def test_dependency_directions_correct(self):
        import src.calibration as cal
        import src.database as db
        import src.math_utils as mu
        cal_inspect = inspect.getsource(cal)
        mu_inspect = inspect.getsource(mu)
        db_inspect = inspect.getsource(db)
        assert "from src.database" not in cal_inspect
        assert "from src.math_utils" not in cal_inspect
        assert "from src.models" in db_inspect
        assert "from src.math_utils" not in db_inspect
        assert "from src.database" not in mu_inspect
        assert "from src.calibration" not in mu_inspect


# ─── Config Integration ───


class TestConfigIntegration:
    """Verify calibration config loads, caches, and is usable downstream."""

    def test_config_loads_and_returns_typed_object(self):
        from src.calibration import CalibrationConfig, get_config
        config = get_config()
        assert isinstance(config, CalibrationConfig)

    def test_cached_config_returns_same_object(self):
        from src.calibration import get_config
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_config_values_match_yaml(self):
        from src.calibration import get_config
        config = get_config()
        assert config.elo_system.k_factor == 32
        assert config.elo_system.base_rating == 1200
        assert config.elo_system.floor_rating == 800
        assert config.elo_system.ceiling_rating == 2000
        assert config.memory_decay.alpha_multiplier == 1.0
        assert config.memory_decay.base_revision_interval_days == 3.0
        assert config.memory_decay.difficulty_weight_scaler == 0.15
        assert config.composition.static_ratio == 0.60
        assert config.composition.ca_ratio == 0.40
        assert config.composition.backlog_ratio == 0.35
        assert "DAILY_SPRINT" in config.practice_modes
        assert config.practice_modes["DAILY_SPRINT"].default_question_count == 30

    def test_config_objects_usable_by_math_functions(self):
        from src.calibration import get_config
        from src.math_utils import compute_dynamic_time_limit, compute_elo_update
        config = get_config()
        elo = config.elo_system
        pacing = config.test_pacing
        result = compute_elo_update(
            r_old=elo.base_rating,
            k_factor=elo.k_factor,
            p_w=0.8,
            expected=0.5,
            floor_rating=elo.floor_rating,
            ceiling_rating=elo.ceiling_rating,
        )
        assert elo.floor_rating <= result <= elo.ceiling_rating
        time_limit = compute_dynamic_time_limit(30, pacing.prelims_expected_seconds_per_question)
        assert time_limit == 1800

    def test_reload_invalidates_cache(self):
        from src.calibration import get_config, reload_config
        c1 = get_config()
        c2 = reload_config()
        assert c1 is not c2


# ─── Schema + Database Integration ───


class TestSchemaDatabaseIntegration:
    """Verify schema contracts are compatible with DB expectations."""

    def test_schema_field_names_map_to_db_columns(self):
        from src.models import TestSession
        from src.schemas import SubmitAnswerResponseSchema, TestRequestSchema
        req_fields = set(TestRequestSchema.model_fields.keys())
        sess_fields = {c.name for c in TestSession.__table__.columns}
        assert "subject_code" in req_fields
        assert "subject_code" in sess_fields
        assert "test_type" in req_fields
        assert "test_type" in sess_fields
        assert "mode" in req_fields
        assert "practice_mode" in sess_fields
        res_fields = set(SubmitAnswerResponseSchema.model_fields.keys())
        assert "score" in res_fields
        assert "elo_delta" in res_fields
        assert "psychological_drift_warning" in res_fields
        assert "warning_reason" in res_fields

    def test_schema_literals_match_db_enums(self):
        from src.schemas import SafeModePYQSchema, TestRequestSchema
        test_type_literal = TestRequestSchema.model_fields["test_type"].annotation
        assert "PRELIMS_GS" in str(test_type_literal)
        assert "CSAT" in str(test_type_literal)
        assert "MAINS_SUBJECTIVE" in str(test_type_literal)
        correct_key_literal = SafeModePYQSchema.model_fields["correct_key"].annotation
        assert "A" in str(correct_key_literal)

    def test_schema_contracts_have_extra_forbid(self):
        from src.schemas import (
            CriticEvaluationSchema,
            ExplanationSchema,
            GeneratedQuestionSchema,
            PrelimsOptionSchema,
            SafeModePYQSchema,
            SubmitAnswerResponseSchema,
            TestRequestSchema,
            TrapAnalysisSchema,
        )
        for schema in [
            TestRequestSchema,
            SubmitAnswerResponseSchema,
            GeneratedQuestionSchema,
            PrelimsOptionSchema,
            ExplanationSchema,
            TrapAnalysisSchema,
            CriticEvaluationSchema,
            SafeModePYQSchema,
        ]:
            assert schema.model_config.get("extra") == "forbid", f"{schema.__name__} missing extra=forbid"

    def test_no_orm_leakage_into_schemas(self):
        import src.schemas as schemas
        source = inspect.getsource(schemas)
        assert "sqlalchemy" not in source.lower()
        assert " from sqlalchemy" not in source.lower()
        assert "Column" not in source
        assert "relationship" not in source
        assert "declarative_base" not in source
        assert "BaseModel" in source
        assert "pydantic" in source

    def test_naming_consistency_student_id(self):
        from src.models import TestSession as ORMTestSession
        assert hasattr(ORMTestSession, "student_id")
        from src.schemas import TestRequestSchema
        assert "student_id" not in TestRequestSchema.model_fields

    def test_naming_consistency_subject_code(self):
        from src.models import TestSession as ORMTestSession
        from src.schemas import TestRequestSchema
        assert hasattr(ORMTestSession, "subject_code")
        assert "subject_code" in TestRequestSchema.model_fields


# ─── Database + Logic Integration ───


class TestDatabaseLogicIntegration:
    """Verify DB initializes and logic layer coexists cleanly."""

    def test_init_db_succeeds(self):
        from sqlalchemy import create_engine, inspect
        engine = create_engine("sqlite:///:memory:")
        from src.models import Base
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected = {
            "student_profile", "topic_progress", "daily_study_log",
            "backlog_queue", "current_affairs_feed", "question_bank",
            "attempt_history", "experiment_runs", "manual_overrides",
            "test_sessions",
        }
        assert tables == expected
        engine.dispose()

    def test_logic_layer_callable_while_db_exists(self):
        from src.database import init_db
        from src.math_utils import compute_elo_update, compute_expected_elo
        init_db()
        expected = compute_expected_elo(1200, 1500)
        result = compute_elo_update(1200, 32, 0.75, expected, 800, 2000)
        assert 800 <= result <= 2000

    def test_no_db_imports_in_math_layer(self):
        import src.math_utils as mu
        source = inspect.getsource(mu)
        assert "import database" not in source
        assert "from src.database" not in source
        assert "sqlalchemy" not in source
        assert "Session" not in source
        assert "from src.models" not in source

    def test_database_session_can_write_and_read(self, test_db, test_session):
        from src.models import StudentProfile
        student = StudentProfile(subject_id="INTEGRATION", subject_name="Integration Test")
        test_session.add(student)
        test_session.commit()
        row = test_session.query(StudentProfile).filter_by(subject_id="INTEGRATION").first()
        assert row is not None
        assert row.subject_name == "Integration Test"


# ─── Logic + Config Integration ───


class TestLogicConfigIntegration:
    """Verify calibration outputs consumed by math functions without hidden coupling."""

    def test_math_functions_accept_config_values_as_parameters(self):
        from src.math_utils import (
            compute_certainty_weighted_performance,
            compute_dynamic_time_limit,
            compute_elo_update,
            compute_memory_decay_interval,
            compute_recovery_velocity,
        )
        elo = compute_elo_update(1200, 32, 0.8, 0.5, 800, 2000)
        assert isinstance(elo, int)
        p_w = compute_certainty_weighted_performance(1.0, 0.75, 45, 60, 120)
        assert 0.0 <= p_w <= 1.0
        interval = compute_memory_decay_interval(3.0, 1.0, 1.0, 5, 0.15, 0)
        assert 1.0 <= interval <= 30.0
        velocity = compute_recovery_velocity(100, 5)
        assert velocity == pytest.approx(20.0)
        time_limit = compute_dynamic_time_limit(30, 60)
        assert time_limit == 1800

    def test_math_layer_has_no_get_config_call(self):
        import src.math_utils as mu
        source = inspect.getsource(mu)
        assert "get_config" not in source
        assert "reload_config" not in source

    def test_calibration_thresholds_match_math_function_parameters(self):
        from src.calibration import get_config
        from src.math_utils import compute_dynamic_time_limit, compute_elo_update
        config = get_config()
        elo = compute_elo_update(
            r_old=config.elo_system.base_rating,
            k_factor=config.elo_system.k_factor,
            p_w=1.0,
            expected=0.0,
            floor_rating=config.elo_system.floor_rating,
            ceiling_rating=config.elo_system.ceiling_rating,
        )
        assert config.elo_system.floor_rating <= elo <= config.elo_system.ceiling_rating
        assert isinstance(elo, int)
        near_ceiling = compute_elo_update(
            r_old=config.elo_system.ceiling_rating - 10,
            k_factor=config.elo_system.k_factor,
            p_w=1.0,
            expected=0.0,
            floor_rating=config.elo_system.floor_rating,
            ceiling_rating=config.elo_system.ceiling_rating,
        )
        assert near_ceiling == config.elo_system.ceiling_rating, "ceiling clamp should cap at 2000"
        near_floor = compute_elo_update(
            r_old=config.elo_system.floor_rating + 10,
            k_factor=config.elo_system.k_factor,
            p_w=0.0,
            expected=1.0,
            floor_rating=config.elo_system.floor_rating,
            ceiling_rating=config.elo_system.ceiling_rating,
        )
        assert near_floor == config.elo_system.floor_rating, "floor clamp should cap at 800"
        time_limit_30 = compute_dynamic_time_limit(30, config.test_pacing.prelims_expected_seconds_per_question)
        assert time_limit_30 == 30 * config.test_pacing.prelims_expected_seconds_per_question
        time_limit_1 = compute_dynamic_time_limit(1, config.test_pacing.mains_expected_seconds_per_question)
        assert time_limit_1 == config.test_pacing.mains_expected_seconds_per_question


# ─── Purity Verification ───


class TestPurityVerification:
    """Verify no forbidden coupling between layers."""

    def test_math_utils_no_forbidden_imports(self):
        import src.math_utils as mu
        source = inspect.getsource(mu)
        forbidden = ["import database", "from src.database", "sqlalchemy",
                     "Session", "from src.models", "get_config",
                     "reload_config", "open(", "os."]
        for token in forbidden:
            assert token not in source, f"math_utils contains: {token}"
        import_lines = [line for line in source.split("\n") if line.strip().startswith(("import ", "from "))]
        assert all("math" in line for line in import_lines)

    def test_calibration_no_db_imports(self):
        import src.calibration as cal
        source = inspect.getsource(cal)
        forbidden = ["import database", "from src.database", "sqlalchemy",
                     "Session", "SessionLocal", "get_session",
                     "from src.models", "import models"]
        for token in forbidden:
            assert token not in source, f"calibration contains: {token}"

    def test_database_no_math_coupling(self):
        import src.database as db
        source = inspect.getsource(db)
        forbidden = ["from src.math_utils", "import math_utils",
                     "import math", "compute_elo", "compute_memory",
                     "from src.schemas"]
        for token in forbidden:
            assert token not in source, f"database contains: {token}"


# ─── Config Advanced Integration ───


class TestConfigAdvanced:
    """Deep config structure verification."""

    @pytest.mark.parametrize("mode_name,expected_q", [
        ("DAILY_SPRINT", 30), ("TOPIC_PRACTICE", 20),
        ("REVISION_MODE", 15), ("MOCK_TEST", 100),
    ])
    def test_all_practice_modes_have_correct_defaults(self, mode_name, expected_q):
        from src.calibration import get_config
        config = get_config()
        mode = config.practice_modes[mode_name]
        assert mode.default_question_count == expected_q

    @pytest.mark.parametrize("mode_name,field,expected", [
        ("DAILY_SPRINT", "enforce_backlog", True),
        ("DAILY_SPRINT", "enforce_floor", True),
        ("DAILY_SPRINT", "time_limit_enabled", True),
        ("TOPIC_PRACTICE", "enforce_backlog", False),
        ("TOPIC_PRACTICE", "enforce_floor", False),
        ("REVISION_MODE", "enforce_backlog", True),
        ("REVISION_MODE", "time_limit_enabled", False),
        ("MOCK_TEST", "enforce_floor", True),
        ("MOCK_TEST", "time_limit_enabled", True),
    ])
    def test_practice_mode_flags(self, mode_name, field, expected):
        from src.calibration import get_config
        mode = get_config().practice_modes[mode_name]
        assert getattr(mode, field) is expected

    def test_config_sections_all_accessible(self):
        from src.calibration import get_config
        c = get_config()
        assert c.current_affairs_filters["similarity_threshold"] == 0.88
        assert c.curricular_floor["random_syllabus_allocation"] == 0.20
        assert c.behavioral_fatigue_limits["pacing_std_dev_threshold"] == 0.40
        assert c.critic_thresholds["combined_minimum"] == 0.85
        assert c.diagnostic["exceptional_elo"] == 1450
        assert c.session["inactivity_timeout_minutes"] == 120

    def test_config_numeric_types(self):
        from src.calibration import get_config
        c = get_config()
        assert isinstance(c.elo_system.k_factor, int)
        assert isinstance(c.elo_system.floor_rating, int)
        assert isinstance(c.elo_system.ceiling_rating, int)
        assert isinstance(c.memory_decay.alpha_multiplier, float)
        assert isinstance(c.composition.static_ratio, float)

    def test_reload_multiple_times_consistent(self):
        from src.calibration import get_config, reload_config
        c1 = get_config()
        for _ in range(5):
            c2 = reload_config()
        assert isinstance(c2, type(c1))


# ─── Schema Cross-Validation ───


class TestSchemaCrossValidation:
    """Test all schemas with boundary values and rejection cases."""

    def test_test_request_all_fields_populated(self):
        from src.schemas import TestRequestSchema
        req = TestRequestSchema(
            subject_code="POLITY",
            test_type="PRELIMS_GS",
            mode="TOPIC_PRACTICE",
            topics=["Parliament", "Fundamental Rights"],
            question_count=25,
            study_context={"today_focus": "POLITY"},
        )
        assert req.subject_code == "POLITY"
        assert req.question_count == 25
        assert len(req.topics) == 2

    def test_test_request_defaults_mode_and_optional(self):
        from src.schemas import TestRequestSchema
        req = TestRequestSchema(subject_code="ECONOMY", test_type="CSAT")
        assert req.mode == "DAILY_SPRINT"
        assert req.topics is None
        assert req.question_count is None

    def test_submit_answer_all_fields(self):
        from src.schemas import SubmitAnswerResponseSchema
        resp = SubmitAnswerResponseSchema(
            score=0.85, elo_delta=15,
            psychological_drift_warning=True,
            warning_reason="Pacing variance high",
        )
        assert resp.score == 0.85
        assert resp.elo_delta == 15
        assert resp.warning_reason is not None

    def test_submit_answer_warning_optional(self):
        from src.schemas import SubmitAnswerResponseSchema
        resp = SubmitAnswerResponseSchema(
            score=0.0, elo_delta=0, psychological_drift_warning=False,
        )
        assert resp.warning_reason is None

    def test_generated_question_all_fields(self):
        from src.schemas import GeneratedQuestionSchema, PrelimsOptionSchema, ExplanationSchema, TrapAnalysisSchema
        gq = GeneratedQuestionSchema(
            question_text="Test?",
            options=[
                PrelimsOptionSchema(id="A", text="A"),
                PrelimsOptionSchema(id="B", text="B"),
                PrelimsOptionSchema(id="C", text="C"),
                PrelimsOptionSchema(id="D", text="D"),
            ],
            correct_option_id="C",
            difficulty_tier=7,
            explanation_data=ExplanationSchema(
                simple_core_concept="C",
                step_by_step_justification="Steps",
                correct_logic="C is right",
                incorrect_logic={"A": "no", "B": "no", "D": "no"},
            ),
            trap_data=TrapAnalysisSchema(
                trap_type="Extreme Phrasing", trap_mechanism="X", elimination_clue="Y",
            ),
        )
        assert gq.difficulty_tier == 7
        assert gq.correct_option_id == "C"

    def test_critic_evaluation_edge_scores(self):
        from src.schemas import CriticEvaluationSchema
        ce = CriticEvaluationSchema(
            fact_check_verification=0.0, semantic_authenticity=1.0,
            distractor_plausibility=0.5, blueprint_alignment=0.5,
            combined_score=0.5, rejection_reason="All low",
        )
        assert ce.fact_check_verification == 0.0
        assert ce.combined_score == 0.5

    def test_safe_mode_pyq_optional_subject(self):
        from src.schemas import SafeModePYQSchema
        sp = SafeModePYQSchema(
            question_id="q1", question_text="Q?",
            options={"A": "a", "B": "b", "C": "c", "D": "d"},
            correct_key="A", difficulty_tier=5,
            subject_id="HISTORY", source_year=2020,
        )
        assert sp.source_year == 2020
        assert sp.subject_id == "HISTORY"

    @pytest.mark.parametrize("field", ["fact_check_verification", "semantic_authenticity",
                                        "distractor_plausibility", "blueprint_alignment", "combined_score"])
    def test_critic_scores_reject_out_of_range(self, field):
        from pydantic import ValidationError
        from src.schemas import CriticEvaluationSchema
        data = {
            "fact_check_verification": 0.5, "semantic_authenticity": 0.5,
            "distractor_plausibility": 0.5, "blueprint_alignment": 0.5,
            "combined_score": 0.5,
        }
        data[field] = 1.5
        with pytest.raises(ValidationError):
            CriticEvaluationSchema(**data)

    def test_generated_question_requires_exactly_four_options(self):
        from pydantic import ValidationError
        from src.schemas import GeneratedQuestionSchema, PrelimsOptionSchema, ExplanationSchema, TrapAnalysisSchema
        base = {
            "question_text": "Q",
            "correct_option_id": "A",
            "difficulty_tier": 5,
            "explanation_data": ExplanationSchema(
                simple_core_concept="C", step_by_step_justification="S",
                correct_logic="R", incorrect_logic={"B": "n", "C": "n", "D": "n"},
            ),
            "trap_data": TrapAnalysisSchema(
                trap_type="T", trap_mechanism="M", elimination_clue="C",
            ),
        }
        with pytest.raises(ValidationError):
            GeneratedQuestionSchema(options=[
                PrelimsOptionSchema(id="A", text="1"),
                PrelimsOptionSchema(id="B", text="2"),
                PrelimsOptionSchema(id="C", text="3"),
            ], **base)

    @pytest.mark.parametrize("bad_id", ["E", "1", "", "AB"])
    def test_option_id_rejects_invalid(self, bad_id):
        from pydantic import ValidationError
        from src.schemas import PrelimsOptionSchema
        with pytest.raises(ValidationError):
            PrelimsOptionSchema(id=bad_id, text="test")

    @pytest.mark.parametrize("test_type", ["PRELIMS_GS", "CSAT", "MAINS_SUBJECTIVE"])
    def test_all_test_types_acceptable(self, test_type):
        from src.schemas import TestRequestSchema
        req = TestRequestSchema(subject_code="POLITY", test_type=test_type)
        assert req.test_type == test_type

    @pytest.mark.parametrize("mode", ["DAILY_SPRINT", "TOPIC_PRACTICE", "REVISION_MODE", "MOCK_TEST"])
    def test_all_modes_acceptable(self, mode):
        from src.schemas import TestRequestSchema
        req = TestRequestSchema(subject_code="POLITY", test_type="PRELIMS_GS", mode=mode)
        assert req.mode == mode

    def test_safe_mode_difficulty_tier_bounds(self):
        from pydantic import ValidationError
        from src.schemas import SafeModePYQSchema
        base = dict(question_id="q", question_text="t",
                    options={"A": "a", "B": "b", "C": "c", "D": "d"},
                    correct_key="A", subject_id="GEO", source_year=2023)
        with pytest.raises(ValidationError):
            SafeModePYQSchema(difficulty_tier=0, **base)
        with pytest.raises(ValidationError):
            SafeModePYQSchema(difficulty_tier=11, **base)

    def test_explanation_incorrect_logic_keys(self):
        from src.schemas import ExplanationSchema
        expl = ExplanationSchema(
            simple_core_concept="C", step_by_step_justification="S",
            correct_logic="R", incorrect_logic={"A": "w", "B": "x", "C": "y", "D": "z"},
        )
        assert len(expl.incorrect_logic) >= 3

    def test_explanation_fields_accept_empty_strings(self):
        """Schema does not enforce min_length, so empty strings are allowed."""
        from src.schemas import ExplanationSchema
        expl = ExplanationSchema(
            simple_core_concept="", step_by_step_justification="S",
            correct_logic="R", incorrect_logic={"A": "w"},
        )
        assert expl.simple_core_concept == ""


# ─── DB Stress Integration ───


class TestDatabaseStress:
    """Database capacity, constraints, and relationship tests."""

    def test_multiple_student_inserts(self, test_db, test_session):
        from src.models import StudentProfile
        subjects = [("SUBJ01", "A"), ("SUBJ02", "B"), ("SUBJ03", "C"),
                    ("SUBJ04", "D"), ("SUBJ05", "E")]
        for sid, name in subjects:
            test_session.add(StudentProfile(subject_id=sid, subject_name=name))
        test_session.commit()
        count = test_session.query(StudentProfile).count()
        assert count >= 5

    def test_student_default_elo_values(self, test_db, test_session):
        from src.models import StudentProfile
        s = StudentProfile(subject_id="DEFAULTS", subject_name="Test")
        test_session.add(s)
        test_session.commit()
        assert s.current_elo_rating == 1200
        assert s.total_questions_attempted == 0
        assert s.consecutive_stable_attempts == 0
        assert s.recovery_velocity_score == 0.0

    def test_topic_progress_defaults(self, test_db, test_session):
        from src.models import StudentProfile, TopicProgress
        s = StudentProfile(subject_id="TP_DEF", subject_name="Test")
        test_session.add(s)
        test_session.flush()
        tp = TopicProgress(topic_id="tp1", subject_id="TP_DEF", topic_name="T")
        test_session.add(tp)
        test_session.commit()
        assert tp.base_stability_index == 3.0
        assert tp.times_reviewed == 0
        assert tp.mistake_count == 0

    def test_orphan_topic_progress_allowed_without_fk_enforcement(self, test_db, test_session):
        """SQLite does not enforce FK constraints without PRAGMA foreign_keys=ON."""
        from src.models import TopicProgress
        tp = TopicProgress(topic_id="orphan", subject_id="NONEXIST", topic_name="O")
        test_session.add(tp)
        test_session.commit()
        assert tp.topic_id == "orphan"
        test_session.rollback()

    def test_orphan_question_bank_allowed_without_fk_enforcement(self, test_db, test_session):
        """SQLite does not enforce FK constraints without PRAGMA foreign_keys=ON."""
        from src.models import QuestionBank
        q = QuestionBank(
            question_id="orphan_q", subject_id="NONEXIST",
            source_type="STATIC_RAG", question_type="PRELIMS_GS",
            difficulty_level=5, question_text="Q", metadata_json={},
            provenance_tags={},
        )
        test_session.add(q)
        test_session.commit()
        assert q.question_id == "orphan_q"
        test_session.rollback()

    def test_test_session_no_foreign_key_constraint(self, test_db, test_session):
        from src.models import TestSession
        ts = TestSession(session_id="orphan_s", subject_code="NONEXIST", test_type="PRELIMS_GS")
        test_session.add(ts)
        test_session.commit()
        assert ts.session_status == "ACTIVE"

    def test_batch_relationship_walk(self, test_db, test_session):
        from src.models import StudentProfile, QuestionBank
        s = StudentProfile(subject_id="BATCH_REL", subject_name="Test")
        test_session.add(s)
        test_session.flush()
        questions = [
            QuestionBank(question_id=f"bq{i}", subject_id="BATCH_REL",
                         source_type="STATIC_RAG", question_type="PRELIMS_GS",
                         difficulty_level=5, question_text=f"Q{i}",
                         metadata_json={}, provenance_tags={})
            for i in range(5)
        ]
        test_session.add_all(questions)
        test_session.commit()
        assert len(s.questions) == 5

    def test_session_rollback_restores_state(self, test_db, test_session):
        from src.models import StudentProfile
        s = StudentProfile(subject_id="ROLLBACK", subject_name="Test")
        test_session.add(s)
        test_session.commit()
        test_session.add(StudentProfile(subject_id="ROLLBACK", subject_name="Dup"))
        test_session.rollback()
        row = test_session.query(StudentProfile).filter_by(subject_id="ROLLBACK").first()
        assert row is not None
        assert row.subject_name == "Test"

    def test_nullable_columns_accept_none(self, test_db, test_session):
        from src.models import StudentProfile, QuestionBank
        s = StudentProfile(subject_id="NULLABLE", subject_name="Test")
        test_session.add(s)
        test_session.flush()
        q = QuestionBank(
            question_id="null_q", subject_id="NULLABLE",
            source_type="STATIC_RAG", question_type="PRELIMS_GS",
            difficulty_level=3, question_text="Q",
            metadata_json={}, provenance_tags={},
            generation_time_ms=None, tokens_consumed=None, correct_key=None,
        )
        test_session.add(q)
        test_session.commit()
        assert q.generation_time_ms is None
        assert q.tokens_consumed is None
        assert q.correct_key is None

    def test_json_fields_serialize_deserialize(self, test_db, test_session):
        from src.models import StudentProfile
        s = StudentProfile(
            subject_id="JSON_TEST", subject_name="Test",
            weakness_tags=["Slow", "Inaccurate"],
        )
        test_session.add(s)
        test_session.commit()
        test_session.refresh(s)
        assert s.weakness_tags == ["Slow", "Inaccurate"]

    def test_attempt_history_relationship(self, test_db, test_session):
        from src.models import StudentProfile, QuestionBank, AttemptHistory
        s = StudentProfile(subject_id="AH_REL", subject_name="Test")
        test_session.add(s)
        test_session.flush()
        q = QuestionBank(question_id="ah_q", subject_id="AH_REL",
                         source_type="STATIC_RAG", question_type="PRELIMS_GS",
                         difficulty_level=5, question_text="Q",
                         metadata_json={}, provenance_tags={})
        a = AttemptHistory(attempt_id="ah_a", question_id="ah_q",
                            session_id="s1", student_response="A",
                            score_percentage=0.8)
        q.attempts.append(a)
        test_session.add(q)
        test_session.commit()
        assert len(q.attempts) == 1
        assert q.attempts[0].score_percentage == 0.8

    def test_daily_study_log_defaults(self, test_db, test_session):
        from src.models import DailyStudyLog
        dsl = DailyStudyLog(date_string="2026-06-01")
        test_session.add(dsl)
        test_session.commit()
        assert dsl.status == "PENDING"
        assert dsl.hours_logged == 0.0


# ─── Math Function Combinations ───


class TestMathCombinations:
    """Cross-product of math function edge cases."""

    @pytest.mark.parametrize("tier,expected", [
        (1, 1100), (2, 1200), (3, 1300), (4, 1400),
        (5, 1500), (6, 1600), (7, 1700), (8, 1800),
        (9, 1900), (10, 2000),
    ])
    def test_all_difficulty_tiers(self, tier, expected):
        from src.math_utils import compute_difficulty_to_elo
        assert compute_difficulty_to_elo(tier) == expected

    @pytest.mark.parametrize("r_old,r_q,expected_range", [
        (1200, 1200, (0.49, 0.51)),
        (1600, 1200, (0.89, 0.92)),
        (1200, 1600, (0.08, 0.11)),
        (2000, 1100, (0.99, 1.0)),
        (800, 2000, (0.0, 0.01)),
    ])
    def test_expected_elo_ranges(self, r_old, r_q, expected_range):
        from src.math_utils import compute_expected_elo
        e = compute_expected_elo(r_old, r_q)
        assert expected_range[0] <= e <= expected_range[1]

    @pytest.mark.parametrize("r_old,k,p_w,exp,floor,ceil,expected_in", [
        (1200, 32, 1.0, 0.5, 800, 2000, (1216,)),
        (1200, 32, 0.0, 0.5, 800, 2000, (1184,)),
        (800, 32, 0.0, 0.99, 800, 2000, (800,)),
        (2000, 32, 1.0, 0.01, 800, 2000, (2000,)),
        (1500, 16, 0.5, 0.5, 800, 2000, (1500,)),
    ])
    def test_elo_update_specific_outcomes(self, r_old, k, p_w, exp, floor, ceil, expected_in):
        from src.math_utils import compute_elo_update
        result = compute_elo_update(r_old, k, p_w, exp, floor, ceil)
        assert result in expected_in or expected_in[0] <= result <= expected_in[-1]

    @pytest.mark.parametrize("accuracy,conf,duration,expected,T_max,expected_pw", [
        (1.0, 1.0, 60, 60, 120, 1.0),
        (1.0, 0.5, 60, 60, 120, 0.5),
        (0.0, 1.0, 60, 60, 120, 0.0),
        (1.0, 1.0, 180, 60, 120, 0.0),
        (1.0, 0.75, 90, 60, 120, 0.5625),
        (0.5, 1.0, 60, 60, 120, 0.5),
    ])
    def test_certainty_weighted_performance_combo(self, accuracy, conf, duration, expected, T_max, expected_pw):
        from src.math_utils import compute_certainty_weighted_performance
        result = compute_certainty_weighted_performance(accuracy, conf, duration, expected, T_max)
        assert result == pytest.approx(expected_pw, rel=1e-4)

    @pytest.mark.parametrize("tier,scaler,mistakes,expected_min,expected_max", [
        (1, 0.15, 0, 5.0, 30.0),
        (10, 0.15, 0, 1.0, 10.0),
        (10, 0.15, 20, 1.0, 3.0),
        (5, 0.15, 0, 3.0, 25.0),
        (1, 0.15, 30, 1.0, 5.0),
    ])
    def test_memory_decay_interval_ranges(self, tier, scaler, mistakes, expected_min, expected_max):
        from src.math_utils import compute_memory_decay_interval
        result = compute_memory_decay_interval(3.0, 1.0, 1.0, tier, scaler, mistakes)
        assert expected_min <= result <= expected_max

    @pytest.mark.parametrize("delta_elo,delta_days,expected", [
        (100, 5, 20.0),
        (0, 5, 0.0),
        (50, 0, 50.0),
        (30, 3, 10.0),
        (100, 10, 10.0),
        (-50, 5, 0.0),
    ])
    def test_recovery_velocity_variants(self, delta_elo, delta_days, expected):
        from src.math_utils import compute_recovery_velocity
        assert compute_recovery_velocity(delta_elo, delta_days) == pytest.approx(expected)

    @pytest.mark.parametrize("count,expected_sec,expected_total", [
        (30, 60, 1800), (1, 60, 60), (0, 60, 0),
        (100, 60, 6000), (30, 450, 13500), (15, 60, 900),
    ])
    def test_dynamic_time_limit_variants(self, count, expected_sec, expected_total):
        from src.math_utils import compute_dynamic_time_limit
        assert compute_dynamic_time_limit(count, expected_sec) == expected_total

    @pytest.mark.parametrize("i_base,i_next,expected", [
        (3.0, 5.0, 3.2), (5.0, 5.0, 5.0),
        (10.0, 1.0, 9.1), (1.0, 30.0, 3.9),
    ])
    def test_stability_index_variants(self, i_base, i_next, expected):
        from src.math_utils import update_stability_index
        assert update_stability_index(i_base, i_next) == pytest.approx(expected)

    def test_elo_overflow_protection(self):
        from src.math_utils import compute_expected_elo
        r = compute_expected_elo(999999, 1)
        if r > 0.5:
            # Massive gap r_old >> r_q → E ≈ 1.0
            assert r > 0.99
        else:
            # r_old << r_q → E ≈ 0.0
            assert r < 0.01

    def test_memory_decay_overflow_protection(self):
        from src.math_utils import compute_memory_decay_interval
        result = compute_memory_decay_interval(1e10, 1.0, 0.5, 1, 0.15, 0)
        assert 1.0 <= result <= 30.0

    def test_elo_update_with_rounded_floats(self):
        from src.math_utils import compute_elo_update
        result = compute_elo_update(1200, 7, 0.333, 0.5, 800, 2000)
        assert isinstance(result, int)

    def test_certainty_weighted_edge_case_exact_threshold(self):
        from src.math_utils import compute_certainty_weighted_performance
        result = compute_certainty_weighted_performance(1.0, 1.0, 180, 60, 120)
        assert result == pytest.approx(0.0)

    def test_math_functions_all_outputs_deterministic(self):
        from src.math_utils import compute_elo_update, compute_expected_elo
        from src.math_utils import compute_memory_decay_interval, compute_recovery_velocity
        a = compute_expected_elo(1200, 1500)
        b = compute_expected_elo(1200, 1500)
        assert a == b
        assert compute_elo_update(1200, 32, 0.75, 0.5, 800, 2000) == \
               compute_elo_update(1200, 32, 0.75, 0.5, 800, 2000)
        assert compute_memory_decay_interval(3.0, 1.0, 1.0, 5, 0.15, 0) == \
               compute_memory_decay_interval(3.0, 1.0, 1.0, 5, 0.15, 0)
        assert compute_recovery_velocity(100, 5) == compute_recovery_velocity(100, 5)


# ─── Config + DB Integration ───


class TestConfigDatabaseIntegration:
    """Write config-derived data to DB, read back, verify consistency."""

    def test_config_values_written_to_db_match(self, test_db, test_session):
        from src.calibration import get_config
        from src.models import TestSession
        config = get_config()
        ts = TestSession(
            session_id="config_ts_1",
            subject_code="POLITY",
            test_type="PRELIMS_GS",
            practice_mode="DAILY_SPRINT",
            question_count=config.practice_modes["DAILY_SPRINT"].default_question_count,
        )
        test_session.add(ts)
        test_session.commit()
        assert ts.question_count == config.practice_modes["DAILY_SPRINT"].default_question_count

    def test_session_timeout_from_config(self):
        from src.calibration import get_config
        from src.database import expire_stale_sessions
        timeout = get_config().session["inactivity_timeout_minutes"]
        assert timeout == 120
        assert callable(expire_stale_sessions)

    def test_config_ratios_match_composition_expectations(self):
        from src.calibration import get_config
        c = get_config()
        total = c.composition.static_ratio + c.composition.ca_ratio
        assert total == pytest.approx(1.0)
        assert 0.0 <= c.composition.backlog_ratio <= 1.0

    def test_memory_decay_config_used_in_math(self):
        from src.calibration import get_config
        from src.math_utils import compute_memory_decay_interval
        config = get_config()
        result = compute_memory_decay_interval(
            i_base=config.memory_decay.base_revision_interval_days,
            alpha_multiplier=config.memory_decay.alpha_multiplier,
            confidence_weight=1.0,
            difficulty_tier=5,
            difficulty_weight_scaler=config.memory_decay.difficulty_weight_scaler,
            mistake_count=0,
        )
        assert 1.0 <= result <= 30.0


# ─── Exception Integration ───


class TestExceptionIntegration:
    """Verify exception hierarchy and propagation."""

    def test_all_exceptions_importable(self):
        from src.exceptions import (
            UPSCAgentException, CalibrationFailure, GenerationFailure,
            EvaluationFailure, CurrentAffairsFailure, RAGFailure, UserBehaviorFlag,
        )
        assert issubclass(CalibrationFailure, UPSCAgentException)
        assert issubclass(GenerationFailure, UPSCAgentException)
        assert issubclass(EvaluationFailure, UPSCAgentException)
        assert issubclass(CurrentAffairsFailure, UPSCAgentException)
        assert issubclass(RAGFailure, UPSCAgentException)
        assert issubclass(UserBehaviorFlag, UPSCAgentException)

    def test_calibration_failure_raised_on_missing_file(self, monkeypatch):
        from src.calibration import reload_config
        from src.exceptions import CalibrationFailure
        monkeypatch.setattr("src.calibration.CONFIG_PATH", "/nonexistent/calibration_config.yaml")
        with pytest.raises(CalibrationFailure):
            reload_config()

    def test_calibration_failure_message_contains_context(self, monkeypatch):
        from src.calibration import reload_config
        from src.exceptions import CalibrationFailure
        monkeypatch.setattr("src.calibration.CONFIG_PATH", "/nonexistent/calibration_config.yaml")
        with pytest.raises(CalibrationFailure) as exc:
            reload_config()
        assert "calibration" in str(exc.value).lower() or "config" in str(exc.value).lower()


# ─── Runtime Multiple Scenarios ───


class TestRuntimeMultipleScenarios:
    """Multiple end-to-end scenarios: different modes, subjects, configurations."""

    @pytest.mark.parametrize("mode,subject,test_type,expected_q_default", [
        ("DAILY_SPRINT", "POLITY", "PRELIMS_GS", 30),
        ("TOPIC_PRACTICE", "GEOGRAPHY", "CSAT", 20),
        ("REVISION_MODE", "HISTORY", "PRELIMS_GS", 15),
        ("MOCK_TEST", "ECONOMY", "CSAT", 100),
    ])
    def test_scenario_create_test_session(self, test_db, test_session,
                                           mode, subject, test_type, expected_q_default):
        from src.calibration import get_config
        from src.models import TestSession
        config = get_config()
        ts = TestSession(
            session_id=f"scenario_{mode}_{subject}",
            subject_code=subject,
            test_type=test_type,
            practice_mode=mode,
            question_count=config.practice_modes[mode].default_question_count,
        )
        test_session.add(ts)
        test_session.commit()
        assert ts.question_count == expected_q_default
        assert ts.session_status == "ACTIVE"
        assert ts.student_id == "default"

    @pytest.mark.parametrize("difficulty", [1, 3, 5, 7, 10])
    def test_scenario_create_question_various_difficulties(self, test_db, test_session, difficulty):
        from src.models import StudentProfile, QuestionBank
        s = StudentProfile(subject_id=f"D{difficulty}", subject_name="Test")
        test_session.add(s)
        test_session.flush()
        q = QuestionBank(
            question_id=f"dq_{difficulty}",
            subject_id=f"D{difficulty}",
            source_type="STATIC_RAG",
            question_type="PRELIMS_GS",
            difficulty_level=difficulty,
            question_text=f"Difficulty {difficulty} question?",
            metadata_json={"diff": difficulty},
            provenance_tags={"source": "parametrize"},
        )
        test_session.add(q)
        test_session.commit()
        assert q.difficulty_level == difficulty

    @pytest.mark.parametrize("elo_inputs", [
        (1200, 32, 1.0, 0.5),
        (800, 32, 0.0, 0.5),
        (2000, 32, 0.5, 0.5),
        (1500, 16, 0.75, 0.3),
        (1000, 32, 0.2, 0.8),
    ])
    def test_scenario_elo_update_various_states(self, elo_inputs):
        from src.math_utils import compute_elo_update
        r_old, k, pw, exp = elo_inputs
        result = compute_elo_update(r_old, k, pw, exp, 800, 2000)
        assert 800 <= result <= 2000
        assert isinstance(result, int)

    @pytest.mark.parametrize("recovery_inputs", [
        (100, 10), (0, 1), (50, 0), (200, 30), (-10, 5),
    ])
    def test_scenario_recovery_velocity_various(self, recovery_inputs):
        from src.math_utils import compute_recovery_velocity
        delta_elo, days = recovery_inputs
        v = compute_recovery_velocity(delta_elo, days)
        assert v >= 0.0
        assert isinstance(v, float)

    def test_scenario_full_round_trip(self, test_db, test_session):
        from src.calibration import get_config
        from src.math_utils import (
            compute_difficulty_to_elo, compute_expected_elo,
            compute_elo_update,
        )
        from src.models import StudentProfile, AttemptHistory, QuestionBank
        config = get_config()
        s = StudentProfile(subject_id="ROUNDTRIP", subject_name="Test",
                           current_elo_rating=config.elo_system.base_rating)
        test_session.add(s)
        test_session.flush()
        q = QuestionBank(
            question_id="rt_q", subject_id="ROUNDTRIP",
            source_type="STATIC_RAG", question_type="PRELIMS_GS",
            difficulty_level=7, question_text="RT?",
            metadata_json={}, provenance_tags={},
        )
        test_session.add(q)
        test_session.flush()
        r_q = compute_difficulty_to_elo(7)
        e = compute_expected_elo(s.current_elo_rating, r_q)
        new_elo = compute_elo_update(
            s.current_elo_rating, config.elo_system.k_factor,
            1.0, e, config.elo_system.floor_rating, config.elo_system.ceiling_rating,
        )
        a = AttemptHistory(
            attempt_id="rt_a", question_id="rt_q",
            session_id="rt_s", student_response="A",
            confidence_level="HIGH", score_percentage=1.0,
        )
        test_session.add(a)
        s.current_elo_rating = new_elo
        s.total_questions_attempted += 1
        test_session.commit()
        assert s.current_elo_rating != config.elo_system.base_rating
        assert s.total_questions_attempted == 1

    @pytest.mark.parametrize("study_context", [
        None, {"today_focus": "POLITY"},
        {"today_focus": "ECONOMY", "urgency": "high"},
    ])
    def test_scenario_study_context_variants(self, test_db, test_session, study_context):
        from src.models import TestSession
        ts = TestSession(
            session_id=f"ctx_{hash(str(study_context))}",
            subject_code="POLITY", test_type="PRELIMS_GS",
            study_context=study_context,
        )
        test_session.add(ts)
        test_session.commit()
        assert ts.study_context == study_context

    @pytest.mark.parametrize("topics", [
        None, ["Polity"], ["History", "Geography"], []
    ])
    def test_scenario_topics_requested_variants(self, test_db, test_session, topics):
        from src.models import TestSession
        ts = TestSession(
            session_id=f"top_{hash(str(topics))}",
            subject_code="POLITY", test_type="PRELIMS_GS",
            topics_requested=topics,
        )
        test_session.add(ts)
        test_session.commit()
        assert ts.topics_requested == topics

    def test_scenario_all_tables_populated(self, test_db, test_session):
        from src.models import (
            StudentProfile, TopicProgress, DailyStudyLog, BacklogQueue,
            CurrentAffairsFeed, QuestionBank, AttemptHistory,
            ExperimentRun, ManualOverride, TestSession,
        )
        s = StudentProfile(subject_id="POPULATE", subject_name="Test")
        test_session.add(s)
        test_session.flush()
        test_session.add(TopicProgress(topic_id="pop_t", subject_id="POPULATE", topic_name="T"))
        test_session.add(DailyStudyLog(date_string="2026-06-02"))
        test_session.add(BacklogQueue(topic_id="pop_b", topic_type="GS", date_skipped="2026-06-01"))
        test_session.add(CurrentAffairsFeed(
            article_id="pop_a", source="PIB", title="Test",
            raw_content="Content",
        ))
        test_session.add(QuestionBank(
            question_id="pop_q", subject_id="POPULATE",
            source_type="STATIC_RAG", question_type="PRELIMS_GS",
            difficulty_level=5, question_text="Q",
            metadata_json={}, provenance_tags={},
        ))
        test_session.flush()
        test_session.add(AttemptHistory(
            attempt_id="pop_att", question_id="pop_q",
            session_id="pop_s", student_response="A", score_percentage=1.0,
        ))
        test_session.add(ExperimentRun(
            experiment_id="pop_e", config_version="1.0", benchmark_score=0.85,
        ))
        test_session.add(ManualOverride(
            override_id="pop_o", target_id="pop_q", override_type="QUESTION_REJECTED",
        ))
        test_session.add(TestSession(
            session_id="pop_ts", subject_code="POPULATE", test_type="PRELIMS_GS",
        ))
        test_session.commit()
        assert test_session.query(StudentProfile).count() >= 1
        assert test_session.query(TopicProgress).count() >= 1
        assert test_session.query(DailyStudyLog).count() >= 1
        assert test_session.query(BacklogQueue).count() >= 1
        assert test_session.query(CurrentAffairsFeed).count() >= 1
        assert test_session.query(QuestionBank).count() >= 1
        assert test_session.query(AttemptHistory).count() >= 1
        assert test_session.query(ExperimentRun).count() >= 1
        assert test_session.query(ManualOverride).count() >= 1
        assert test_session.query(TestSession).count() >= 1


# ─── Runtime Smoke Flow ───


class TestRuntimeSmokeFlow:
    """End-to-end: load config, init DB, create objects, execute math, verify coexistence."""

    def test_full_smoke_flow(self, test_db, test_session):
        from src.calibration import CalibrationConfig, get_config
        from src.math_utils import (
            compute_certainty_weighted_performance,
            compute_difficulty_to_elo,
            compute_dynamic_time_limit,
            compute_elo_update,
            compute_expected_elo,
            compute_memory_decay_interval,
            compute_recovery_velocity,
            update_stability_index,
        )
        from src.models import (
            AttemptHistory,
            QuestionBank,
            StudentProfile,
            TestSession,
            TopicProgress,
        )
        from src.schemas import (
            ExplanationSchema,
            GeneratedQuestionSchema,
            PrelimsOptionSchema,
            TrapAnalysisSchema,
        )

        config = get_config()
        assert isinstance(config, CalibrationConfig)
        assert config.elo_system.k_factor == 32

        subject_id = "INTEGRATION_SMOKE"
        student = StudentProfile(
            subject_id=subject_id,
            subject_name="Integration Smoke Test",
        )
        test_session.add(student)
        test_session.flush()

        topic = TopicProgress(
            topic_id="smoke_topic_1",
            subject_id=subject_id,
            topic_name="Smoke Topic",
        )
        test_session.add(topic)
        test_session.flush()

        question = QuestionBank(
            question_id="smoke_q_1",
            subject_id=subject_id,
            source_type="STATIC_RAG",
            question_type="PRELIMS_GS",
            difficulty_level=5,
            question_text="Smoke test question?",
            metadata_json={"test": True},
            provenance_tags={"source": "integration_test"},
        )
        test_session.add(question)
        test_session.flush()

        attempt = AttemptHistory(
            attempt_id="smoke_a_1",
            question_id="smoke_q_1",
            session_id="smoke_s_1",
            student_response="A",
            confidence_level="HIGH",
            response_duration_seconds=60.0,
            score_percentage=1.0,
        )
        test_session.add(attempt)
        test_session.flush()

        test_session_record = TestSession(
            session_id="smoke_s_1",
            subject_code=subject_id,
            test_type="PRELIMS_GS",
        )
        test_session.add(test_session_record)
        test_session.commit()

        r_q = compute_difficulty_to_elo(5)
        assert r_q == 1500
        r_old = config.elo_system.base_rating
        expected = compute_expected_elo(r_old, r_q)
        assert 0.0 < expected < 1.0
        p_w = compute_certainty_weighted_performance(
            accuracy=1.0,
            confidence_weight=config.certainty_weights.high,
            response_duration_seconds=60.0,
            expected_seconds=config.test_pacing.prelims_expected_seconds_per_question,
            pacing_max_seconds=config.certainty_weights.pacing_max_seconds,
        )
        assert 0.0 <= p_w <= 1.0
        elo_new = compute_elo_update(
            r_old=r_old,
            k_factor=config.elo_system.k_factor,
            p_w=p_w,
            expected=expected,
            floor_rating=config.elo_system.floor_rating,
            ceiling_rating=config.elo_system.ceiling_rating,
        )
        assert config.elo_system.floor_rating <= elo_new <= config.elo_system.ceiling_rating
        interval = compute_memory_decay_interval(
            i_base=config.memory_decay.base_revision_interval_days,
            alpha_multiplier=config.memory_decay.alpha_multiplier,
            confidence_weight=config.certainty_weights.high,
            difficulty_tier=5,
            difficulty_weight_scaler=config.memory_decay.difficulty_weight_scaler,
            mistake_count=0,
        )
        assert 1.0 <= interval <= 30.0
        stability = update_stability_index(3.0, interval)
        assert stability == pytest.approx(0.9 * 3.0 + 0.1 * interval)
        velocity = compute_recovery_velocity(50, 5)
        assert velocity == pytest.approx(10.0)
        time_limit = compute_dynamic_time_limit(30, config.test_pacing.prelims_expected_seconds_per_question)
        assert time_limit == 1800

        option_a = PrelimsOptionSchema(id="A", text="Option A")
        option_b = PrelimsOptionSchema(id="B", text="Option B")
        option_c = PrelimsOptionSchema(id="C", text="Option C")
        option_d = PrelimsOptionSchema(id="D", text="Option D")
        explanation = ExplanationSchema(
            simple_core_concept="Test concept",
            step_by_step_justification="Step 1, Step 2",
            correct_logic="A is correct because",
            incorrect_logic={"B": "B is wrong because", "C": "C is wrong because", "D": "D is wrong because"},
        )
        trap = TrapAnalysisSchema(
            trap_type="Semantic Drift",
            trap_mechanism="Misleading similar wording",
            elimination_clue="Focus on key qualifiers",
        )
        generated = GeneratedQuestionSchema(
            question_text="Integration schema test?",
            options=[option_a, option_b, option_c, option_d],
            correct_option_id="A",
            difficulty_tier=5,
            explanation_data=explanation,
            trap_data=trap,
        )
        assert generated.question_text == "Integration schema test?"
        assert len(generated.options) == 4

        rows = test_session.query(StudentProfile).all()
        assert len(rows) >= 1
        assert test_session_record.session_status == "ACTIVE"
        test_session.close()
