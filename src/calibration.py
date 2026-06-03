import os
import yaml
from typing import Dict, Any, Optional
from pydantic import BaseModel, ConfigDict
from src.exceptions import CalibrationFailure

class EloSystemConfig(BaseModel):
    k_factor: int
    base_rating: int
    floor_rating: int
    ceiling_rating: int

class TestPacingConfig(BaseModel):
    prelims_expected_seconds_per_question: int
    mains_expected_seconds_per_question: int
    csat_expected_seconds_per_question: int

class CertaintyWeightsConfig(BaseModel):
    high: float
    medium: float
    low: float
    pacing_max_seconds: int

class MemoryDecayConfig(BaseModel):
    alpha_multiplier: float
    base_revision_interval_days: float
    difficulty_weight_scaler: float

class CompositionConfig(BaseModel):
    static_ratio: float
    ca_ratio: float
    backlog_ratio: float

class PracticeModeConfig(BaseModel):
    default_question_count: int
    enforce_backlog: bool
    enforce_floor: bool
    time_limit_enabled: bool

class CalibrationConfig(BaseModel):
    """Strongly typed wrapper for the calibration configuration."""
    model_config = ConfigDict(extra="forbid")
    
    elo_system: EloSystemConfig
    test_pacing: TestPacingConfig
    certainty_weights: CertaintyWeightsConfig
    memory_decay: MemoryDecayConfig
    composition: CompositionConfig
    practice_modes: Dict[str, PracticeModeConfig]
    
    # Keeping less critical sections as Dict[str, Any] to maintain strict schema flexibility
    current_affairs_filters: Dict[str, Any]
    curricular_floor: Dict[str, Any]
    behavioral_fatigue_limits: Dict[str, Any]
    critic_thresholds: Dict[str, Any]
    diagnostic: Dict[str, Any]
    scraper: Dict[str, Any]
    pdf: Dict[str, Any]
    session: Dict[str, Any]
    evaluator: Dict[str, Any]

_cached_config: Optional[CalibrationConfig] = None
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "calibration_config.yaml")

def get_config() -> CalibrationConfig:
    """Returns the cached configuration singleton. Parses YAML on first call."""
    global _cached_config
    if _cached_config is None:
        _cached_config = reload_config()
    return _cached_config

def reload_config() -> CalibrationConfig:
    """Forces a reload of the calibration YAML from disk, validating against Pydantic schema."""
    global _cached_config
    if not os.path.exists(CONFIG_PATH):
        raise CalibrationFailure(f"Configuration file not found at {CONFIG_PATH}")
    
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _cached_config = CalibrationConfig(**data)
        return _cached_config
    except Exception as e:
        raise CalibrationFailure(f"Failed to load or validate calibration config: {str(e)}") from e
