import textwrap

import pytest

from src.calibration import CalibrationConfig, get_config, reload_config
from src.exceptions import CalibrationFailure


@pytest.fixture(autouse=True)
def reset_config_cache():
    import src.calibration as cal
    cal._cached_config = None
    yield
    cal._cached_config = None


def test_config_loads_successfully():
    config = get_config()
    assert isinstance(config, CalibrationConfig)
    assert config.elo_system.k_factor == 32
    assert config.elo_system.floor_rating == 800
    assert config.elo_system.ceiling_rating == 2000
    assert isinstance(config.practice_modes, dict)
    assert "DAILY_SPRINT" in config.practice_modes


def test_get_config_returns_same_object_on_repeated_calls():
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2


def test_reload_config_returns_new_object():
    c1 = get_config()
    c2 = reload_config()
    assert c1 is not c2
    assert isinstance(c2, CalibrationConfig)


def test_missing_config_raises_calibration_failure(monkeypatch):
    monkeypatch.setattr("src.calibration.CONFIG_PATH", "/nonexistent/path.yaml")
    with pytest.raises(CalibrationFailure):
        reload_config()


def test_malformed_yaml_raises_calibration_failure(tmp_path, monkeypatch):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("{{ broken yaml: [}", encoding="utf-8")
    monkeypatch.setattr("src.calibration.CONFIG_PATH", str(bad_yaml))
    with pytest.raises(CalibrationFailure):
        reload_config()


def test_invalid_schema_values_fail(tmp_path, monkeypatch):
    wrong_types = tmp_path / "wrong.yaml"
    wrong_types.write_text(textwrap.dedent("""\
        elo_system:
          k_factor: "not_an_int"
          base_rating: 1200
          floor_rating: 800
          ceiling_rating: 2000
        test_pacing:
          prelims_expected_seconds_per_question: 60
          mains_expected_seconds_per_question: 450
          csat_expected_seconds_per_question: 60
        certainty_weights:
          high: 1.0
          medium: 0.75
          low: 0.5
          pacing_max_seconds: 120
        current_affairs_filters: {}
        memory_decay:
          alpha_multiplier: 1.0
          base_revision_interval_days: 3.0
          difficulty_weight_scaler: 0.15
        curricular_floor: {}
        composition:
          static_ratio: 0.60
          ca_ratio: 0.40
          backlog_ratio: 0.35
        behavioral_fatigue_limits: {}
        critic_thresholds: {}
        diagnostic: {}
        scraper: {}
        pdf: {}
        session: {}
        practice_modes:
          DAILY_SPRINT:
            default_question_count: 30
            enforce_backlog: true
            enforce_floor: true
            time_limit_enabled: true
    """), encoding="utf-8")
    monkeypatch.setattr("src.calibration.CONFIG_PATH", str(wrong_types))
    with pytest.raises(CalibrationFailure):
        reload_config()


def test_forbidden_extra_keys_fail(tmp_path, monkeypatch):
    extra_keys = tmp_path / "extra.yaml"
    extra_keys.write_text(textwrap.dedent("""\
        elo_system:
          k_factor: 32
          base_rating: 1200
          floor_rating: 800
          ceiling_rating: 2000
        test_pacing:
          prelims_expected_seconds_per_question: 60
          mains_expected_seconds_per_question: 450
          csat_expected_seconds_per_question: 60
        certainty_weights:
          high: 1.0
          medium: 0.75
          low: 0.5
          pacing_max_seconds: 120
        current_affairs_filters: {}
        memory_decay:
          alpha_multiplier: 1.0
          base_revision_interval_days: 3.0
          difficulty_weight_scaler: 0.15
        curricular_floor: {}
        composition:
          static_ratio: 0.60
          ca_ratio: 0.40
          backlog_ratio: 0.35
        behavioral_fatigue_limits: {}
        critic_thresholds: {}
        diagnostic: {}
        scraper: {}
        pdf: {}
        session: {}
        practice_modes:
          DAILY_SPRINT:
            default_question_count: 30
            enforce_backlog: true
            enforce_floor: true
            time_limit_enabled: true
        unknown_key: will_fail
    """), encoding="utf-8")
    monkeypatch.setattr("src.calibration.CONFIG_PATH", str(extra_keys))
    with pytest.raises(CalibrationFailure):
        reload_config()


def test_missing_yaml_file_raises_calibration_failure(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist.yaml"
    monkeypatch.setattr("src.calibration.CONFIG_PATH", str(missing))
    with pytest.raises(CalibrationFailure):
        reload_config()


def test_no_hidden_db_imports():
    import src.calibration as cal
    with open(cal.__file__, encoding="utf-8") as f:
        source = f.read()
    assert "import database" not in source
    assert "from src.database" not in source
    assert "sqlalchemy" not in source
    assert "Session" not in source


def test_no_hidden_session_imports():
    import src.calibration as cal
    with open(cal.__file__, encoding="utf-8") as f:
        source = f.read()
    assert "get_session" not in source
    assert "SessionLocal" not in source


def test_practice_modes_accessible():
    config = get_config()
    modes = config.practice_modes
    dm = modes["DAILY_SPRINT"]
    assert dm.default_question_count == 30
    assert dm.enforce_floor is True
    assert dm.time_limit_enabled is True
    tm = modes["TOPIC_PRACTICE"]
    assert tm.default_question_count == 20
    assert tm.enforce_backlog is False
    rm = modes["REVISION_MODE"]
    assert rm.default_question_count == 15
    assert rm.time_limit_enabled is False
    mm = modes["MOCK_TEST"]
    assert mm.default_question_count == 100
    assert mm.enforce_floor is True
