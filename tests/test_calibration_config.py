from pathlib import Path

import yaml

CONFIG_PATH = Path("src/calibration_config.yaml")


def load_config() -> dict[str, object]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_calibration_config_parses_as_yaml_mapping() -> None:
    config = load_config()

    assert isinstance(config, dict)


def test_calibration_config_contains_audit_required_blocks() -> None:
    config = load_config()

    for required_block in [
        "elo_system",
        "test_pacing",
        "certainty_weights",
        "memory_decay",
        "curricular_floor",
        "composition",
        "critic_thresholds",
    ]:
        assert required_block in config


def test_calibration_config_contains_phase_one_contradiction_fixes() -> None:
    config = load_config()

    assert config["test_pacing"] == {
        "prelims_expected_seconds_per_question": 60,
        "mains_expected_seconds_per_question": 450,
        "csat_expected_seconds_per_question": 60,
    }
    assert config["elo_system"]["floor_rating"] == 800
    assert config["elo_system"]["ceiling_rating"] == 2000


def test_calibration_config_composition_ratios_match_locked_architecture() -> None:
    config = load_config()

    assert config["curricular_floor"]["random_syllabus_allocation"] == 0.20
    assert config["composition"]["static_ratio"] == 0.60
    assert config["composition"]["ca_ratio"] == 0.40
    assert config["composition"]["backlog_ratio"] == 0.35
