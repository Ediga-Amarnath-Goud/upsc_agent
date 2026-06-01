import math

def compute_difficulty_to_elo(difficulty_tier: int) -> int:
    """Maps a 1-10 difficulty tier to an Elo rating base."""
    tier = max(1, min(10, difficulty_tier))
    return tier * 100 + 1000

def compute_expected_elo(r_old: int, r_question: int) -> float:
    """Computes expected win probability against a question (E)."""
    if r_old < 0 or r_question < 0:
        raise ValueError("Ratings cannot be negative.")
    try:
        return 1.0 / (1.0 + math.pow(10, (r_question - r_old) / 400.0))
    except OverflowError:
        return 0.0 if r_question > r_old else 1.0

def compute_elo_update(
    r_old: int, 
    k_factor: int, 
    p_w: float, 
    expected: float, 
    floor_rating: int, 
    ceiling_rating: int
) -> int:
    """Updates Elo based on Certainty-Weighted Performance (P_w)."""
    if p_w < 0.0 or p_w > 1.0:
        raise ValueError("P_w must be between 0.0 and 1.0")
    if expected < 0.0 or expected > 1.0:
        raise ValueError("Expected probability must be between 0.0 and 1.0")
        
    r_new = r_old + k_factor * (p_w - expected)
    
    # Clamp to configured [floor, ceiling] limits
    return max(floor_rating, min(ceiling_rating, int(round(r_new))))

def compute_certainty_weighted_performance(
    accuracy: float, 
    confidence_weight: float, 
    response_duration_seconds: float, 
    expected_seconds: float, 
    pacing_max_seconds: float
) -> float:
    """Calculates Certainty-Weighted Performance Vector (P_w) with time penalties."""
    if pacing_max_seconds <= 0 or expected_seconds <= 0:
        raise ValueError("Time thresholds must be positive")
    
    if accuracy < 0.0 or accuracy > 1.0:
        raise ValueError("Accuracy must be between 0.0 and 1.0")
        
    delta_t = abs(response_duration_seconds - expected_seconds)
    time_penalty = 1.0 - (delta_t / pacing_max_seconds)
    time_penalty = max(0.0, min(1.0, time_penalty))
    
    p_w = accuracy * confidence_weight * time_penalty
    return max(0.0, min(1.0, p_w))

def compute_memory_decay_interval(
    i_base: float, 
    alpha_multiplier: float, 
    confidence_weight: float, 
    difficulty_tier: int,
    difficulty_weight_scaler: float,
    mistake_count: int
) -> float:
    """Calculates the next revision interval in days (I_next)."""
    if i_base <= 0:
        raise ValueError("i_base must be positive")
        
    tier = max(1, min(10, difficulty_tier))
    
    # Compute the D_t modifier combining tier weight and past mistakes
    d_t = (tier * difficulty_weight_scaler) + (mistake_count * 0.1)
    
    exponent = alpha_multiplier * confidence_weight * (2.0 - d_t)
    
    # Clamp exponent to prevent math.exp overflow/underflow
    exponent = max(-20.0, min(20.0, exponent))
        
    i_next = i_base * math.exp(exponent)
    
    # Bound final interval to [1.0, 30.0] days per C-03 refinement
    return max(1.0, min(30.0, i_next))

def update_stability_index(i_base: float, i_next: float) -> float:
    """Updates the baseline stability index."""
    if i_base <= 0 or i_next <= 0:
        raise ValueError("Intervals must be positive")
    return (0.9 * i_base) + (0.1 * i_next)

def compute_recovery_velocity(delta_elo: int, delta_days: float) -> float:
    """Computes recovery velocity score (Elo points recovered per day)."""
    if delta_elo < 0:
        return 0.0
    effective_days = max(1.0, delta_days)
    return float(delta_elo) / effective_days

def compute_dynamic_time_limit(question_count: int, expected_seconds_per_question: int) -> int:
    """Computes the total allowed time limit in seconds."""
    if question_count < 0 or expected_seconds_per_question < 0:
        raise ValueError("Inputs cannot be negative")
    return question_count * expected_seconds_per_question
