# Custom exceptions for UPSC Adaptive AI Orchestrator

class UPSCAgentException(Exception):
    """Base exception for all custom UPSC agent errors."""
    pass

class GenerationFailure(UPSCAgentException):
    """Raised when question generation fails."""
    pass

class EvaluationFailure(UPSCAgentException):
    """Raised when answer evaluation fails."""
    pass

class CalibrationFailure(UPSCAgentException):
    """Raised when calibration config is missing or malformed."""
    pass

class CurrentAffairsFailure(UPSCAgentException):
    """Raised when scraping or current affairs ingestion fails."""
    pass

class RAGFailure(UPSCAgentException):
    """Raised when ChromaDB retrieval or insertion fails."""
    pass

class UserBehaviorFlag(UPSCAgentException):
    """Raised when anomalous user behavior (like pacing drift) is detected."""
    pass
