import pytest

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

# ─── Difficulty → Elo ───


class TestDifficultyToElo:
    def test_tier_1_maps_to_1100(self):
        assert compute_difficulty_to_elo(1) == 1100

    def test_tier_10_maps_to_2000(self):
        assert compute_difficulty_to_elo(10) == 2000

    def test_tier_5_maps_to_1500(self):
        assert compute_difficulty_to_elo(5) == 1500

    def test_below_minimum_clamps_to_1(self):
        assert compute_difficulty_to_elo(0) == 1100

    def test_above_maximum_clamps_to_10(self):
        assert compute_difficulty_to_elo(11) == 2000

    def test_negative_tier_clamps_to_1(self):
        assert compute_difficulty_to_elo(-5) == 1100


# ─── Expected Elo ───


class TestExpectedElo:
    def test_equal_ratings(self):
        assert compute_expected_elo(1200, 1200) == pytest.approx(0.5, rel=1e-9)

    def test_higher_rating_greater_than_0_5(self):
        assert compute_expected_elo(1600, 1200) > 0.5

    def test_lower_rating_less_than_0_5(self):
        assert compute_expected_elo(1200, 1600) < 0.5

    def test_overwhelming_favorite(self):
        assert compute_expected_elo(2000, 1100) > 0.99

    def test_negative_ratings_raise_value_error(self):
        with pytest.raises(ValueError):
            compute_expected_elo(-100, 1200)

    def test_negative_question_rating_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_expected_elo(1200, -100)

    def test_deterministic(self):
        assert compute_expected_elo(1200, 1500) == compute_expected_elo(1200, 1500)


# ─── Elo Update ───


class TestEloUpdate:
    def test_win_increases_rating(self):
        result = compute_elo_update(1200, 32, 1.0, 0.5, 800, 2000)
        assert result > 1200

    def test_loss_decreases_rating(self):
        result = compute_elo_update(1200, 32, 0.0, 0.5, 800, 2000)
        assert result < 1200

    def test_floor_clamping(self):
        result = compute_elo_update(800, 32, 0.0, 0.99, 800, 2000)
        assert result >= 800

    def test_ceiling_clamping(self):
        result = compute_elo_update(2000, 32, 1.0, 0.01, 800, 2000)
        assert result <= 2000

    def test_zero_k_factor_no_change(self):
        result = compute_elo_update(1200, 0, 1.0, 0.5, 800, 2000)
        assert result == 1200

    def test_rounding_behavior(self):
        result = compute_elo_update(1200, 7, 1.0, 0.5, 800, 2000)
        assert isinstance(result, int)

    def test_invalid_p_w_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_elo_update(1200, 32, -0.1, 0.5, 800, 2000)

    def test_negative_p_w_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_elo_update(1200, 32, 1.5, 0.5, 800, 2000)

    def test_deterministic(self):
        args = (1200, 32, 0.75, 0.5, 800, 2000)
        assert compute_elo_update(*args) == compute_elo_update(*args)


# ─── Certainty-Weighted Performance ───


class TestCertaintyWeightedPerformance:
    def test_correct_high_conf_on_time(self):
        result = compute_certainty_weighted_performance(1.0, 1.0, 60, 60, 120)
        assert result == pytest.approx(1.0)

    def test_correct_low_conf_on_time(self):
        result = compute_certainty_weighted_performance(1.0, 0.5, 60, 60, 120)
        assert result == pytest.approx(0.5)

    def test_wrong_answer_zero_performance(self):
        result = compute_certainty_weighted_performance(0.0, 1.0, 60, 60, 120)
        assert result == pytest.approx(0.0)

    def test_correct_high_conf_extreme_overrun_clamped_to_zero(self):
        result = compute_certainty_weighted_performance(1.0, 1.0, 300, 60, 120)
        assert result == pytest.approx(0.0)

    def test_p_w_bounds_never_negative(self):
        result = compute_certainty_weighted_performance(1.0, 1.0, 600, 60, 120)
        assert result >= 0.0

    def test_p_w_bounds_never_exceeds_one(self):
        result = compute_certainty_weighted_performance(1.0, 1.0, 60, 60, 120)
        assert result <= 1.0

    def test_negative_accuracy_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_certainty_weighted_performance(-0.5, 1.0, 60, 60, 120)

    def test_accuracy_above_one_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_certainty_weighted_performance(1.5, 1.0, 60, 60, 120)

    def test_zero_pacing_max_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_certainty_weighted_performance(1.0, 1.0, 60, 60, 0)

    def test_zero_expected_seconds_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_certainty_weighted_performance(1.0, 1.0, 60, 0, 120)

    def test_mid_performance_partial_confidence_and_delay(self):
        result = compute_certainty_weighted_performance(1.0, 0.75, 90, 60, 120)
        expected = 1.0 * 0.75 * (1.0 - (30.0 / 120.0))
        assert result == pytest.approx(expected)

    def test_deterministic(self):
        args = (0.75, 1.0, 45, 60, 120)
        assert compute_certainty_weighted_performance(*args) == compute_certainty_weighted_performance(*args)


# ─── Memory Decay Interval ───


class TestMemoryDecayInterval:
    def test_basic_interval_computed(self):
        result = compute_memory_decay_interval(3.0, 1.0, 1.0, 5, 0.15, 0)
        assert 1.0 <= result <= 30.0

    def test_easy_topic_longer_interval(self):
        easy = compute_memory_decay_interval(3.0, 1.0, 1.0, 1, 0.15, 0)
        hard = compute_memory_decay_interval(3.0, 1.0, 1.0, 10, 0.15, 0)
        assert easy >= hard

    def test_many_mistakes_shorter_interval(self):
        no_mistakes = compute_memory_decay_interval(3.0, 1.0, 1.0, 10, 0.15, 0)
        many_mistakes = compute_memory_decay_interval(3.0, 1.0, 1.0, 10, 0.15, 20)
        assert many_mistakes <= no_mistakes

    def test_lower_bound_floor_one_day(self):
        result = compute_memory_decay_interval(3.0, 1.0, 0.5, 10, 0.15, 100)
        assert result >= 1.0

    def test_upper_bound_ceiling_thirty_days(self):
        result = compute_memory_decay_interval(3.0, 1.0, 1.0, 1, 0.15, 0)
        assert result <= 30.0

    def test_zero_i_base_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_memory_decay_interval(0, 1.0, 1.0, 5, 0.15, 0)

    def test_negative_i_base_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_memory_decay_interval(-1.0, 1.0, 1.0, 5, 0.15, 0)

    def test_difficulty_tier_clamped_below_1(self):
        result = compute_memory_decay_interval(3.0, 1.0, 1.0, 0, 0.15, 0)
        assert 1.0 <= result <= 30.0

    def test_difficulty_tier_clamped_above_10(self):
        result = compute_memory_decay_interval(3.0, 1.0, 1.0, 15, 0.15, 0)
        assert 1.0 <= result <= 30.0

    def test_deterministic(self):
        args = (3.0, 1.0, 1.0, 5, 0.15, 0)
        assert compute_memory_decay_interval(*args) == compute_memory_decay_interval(*args)


# ─── Stability Index Update ───


class TestStabilityIndex:
    def test_weighted_average(self):
        result = update_stability_index(3.0, 5.0)
        assert result == pytest.approx(0.9 * 3.0 + 0.1 * 5.0)

    def test_equal_values_no_change(self):
        result = update_stability_index(5.0, 5.0)
        assert result == pytest.approx(5.0)

    def test_zero_i_base_raises_value_error(self):
        with pytest.raises(ValueError):
            update_stability_index(0, 5.0)

    def test_zero_i_next_raises_value_error(self):
        with pytest.raises(ValueError):
            update_stability_index(3.0, 0)

    def test_deterministic(self):
        assert update_stability_index(4.0, 2.0) == update_stability_index(4.0, 2.0)


# ─── Recovery Velocity ───


class TestRecoveryVelocity:
    def test_positive_recovery(self):
        result = compute_recovery_velocity(100, 5)
        assert result == pytest.approx(20.0)

    def test_zero_delta_days_floors_to_one(self):
        result = compute_recovery_velocity(50, 0)
        assert result == pytest.approx(50.0)

    def test_negative_delta_elo_returns_zero(self):
        result = compute_recovery_velocity(-50, 5)
        assert result == pytest.approx(0.0)

    def test_zero_delta_elo_returns_zero(self):
        result = compute_recovery_velocity(0, 5)
        assert result == pytest.approx(0.0)

    def test_float_delta_days(self):
        result = compute_recovery_velocity(30, 2.5)
        assert result == pytest.approx(12.0)

    def test_deterministic(self):
        assert compute_recovery_velocity(100, 5) == compute_recovery_velocity(100, 5)


# ─── Dynamic Time Limit ───


class TestDynamicTimeLimit:
    def test_simple_multiplication(self):
        assert compute_dynamic_time_limit(30, 60) == 1800

    def test_zero_question_count(self):
        assert compute_dynamic_time_limit(0, 60) == 0

    def test_single_question(self):
        assert compute_dynamic_time_limit(1, 450) == 450

    def test_negative_count_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_dynamic_time_limit(-1, 60)

    def test_negative_expected_seconds_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_dynamic_time_limit(30, -60)

    def test_large_values(self):
        assert compute_dynamic_time_limit(100, 60) == 6000

    def test_deterministic(self):
        assert compute_dynamic_time_limit(30, 60) == compute_dynamic_time_limit(30, 60)


# ─── General Purity ───


class TestGeneralPurity:
    def test_no_config_loading_in_source(self):
        import src.math_utils as mu
        with open(mu.__file__, encoding="utf-8") as f:
            source = f.read()
        assert "calibration" not in source.lower()
        assert "get_config" not in source
        assert "reload_config" not in source

    def test_no_filesystem_access(self):
        import src.math_utils as mu
        with open(mu.__file__, encoding="utf-8") as f:
            source = f.read()
        assert "open(" not in source
        assert "os." not in source
        assert "sqlalchemy" not in source
        assert "Session" not in source

    def test_no_db_imports(self):
        import src.math_utils as mu
        with open(mu.__file__, encoding="utf-8") as f:
            source = f.read()
        assert "import database" not in source
        assert "from src.database" not in source
        assert "sqlalchemy" not in source
        assert "Session" not in source

    def test_no_side_effects_on_import(self):
        import src.math_utils as mu
        assert callable(mu.compute_elo_update)
        assert callable(mu.compute_expected_elo)

    def test_only_math_stdlib_imported(self):
        import src.math_utils as mu
        with open(mu.__file__, encoding="utf-8") as f:
            source = f.read()
        import_lines = [line for line in source.split("\n") if line.startswith("import ") or line.startswith("from ")]
        assert all("math" in line for line in import_lines)
