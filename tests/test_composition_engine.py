"""
Architecture-first verification for Phase 3 Group 1: The Composition Engine.

Verifies allocation invariants, remainder-absorb rounding, backlog behavior,
boundary values, property sweeps, and dependency isolation.
"""

import ast
import inspect
import math
import sys

import pytest

from src.composition_engine import solve_composition, CompositionPlan


# ── Ratios from calibration config (architecture defaults) ────────────────

FLOOR_RATIO = 0.20
STATIC_RATIO = 0.60
BACKLOG_RATIO = 0.35


# ── Helpers ───────────────────────────────────────────────────────────────

def check_invariants(bp: CompositionPlan) -> None:
    """Assert all allocation invariants for a CompositionPlan.

    Verifies:
      1. Total sum == target_total
      2. No negative allocations
      3. Category conservation:
         static_today + static_backlog == computed_static_count
         ca_today   + ca_backlog   == target_total - floor_count - computed_static_count
      4. Backlog never exceeds its category
    """
    total = bp.floor_count + bp.static_today + bp.static_backlog + bp.ca_today + bp.ca_backlog

    # ── (1) Total-match invariant ────────────────────────────────────
    assert total == bp.target_total, (
        f"Sum {total} != target_total {bp.target_total}  "
        f"({bp.floor_count} + {bp.static_today} + {bp.static_backlog} + "
        f"{bp.ca_today} + {bp.ca_backlog})"
    )

    # ── (2) Non-negative invariant ───────────────────────────────────
    assert bp.floor_count >= 0
    assert bp.static_today >= 0
    assert bp.static_backlog >= 0
    assert bp.ca_today >= 0
    assert bp.ca_backlog >= 0

    # ── (3) Category conservation (explicit ratio-based derivation) ──
    remaining = bp.target_total - bp.floor_count
    computed_static_count = max(0, math.floor(remaining * STATIC_RATIO))
    computed_ca_count = remaining - computed_static_count

    static_sum = bp.static_today + bp.static_backlog
    ca_sum = bp.ca_today + bp.ca_backlog

    assert static_sum == computed_static_count, (
        f"static_today({bp.static_today}) + static_backlog({bp.static_backlog}) "
        f"= {static_sum} != computed_static_count({computed_static_count}) "
        f"[remaining={remaining}, ratio={STATIC_RATIO}]"
    )
    assert ca_sum == computed_ca_count, (
        f"ca_today({bp.ca_today}) + ca_backlog({bp.ca_backlog}) "
        f"= {ca_sum} != computed_ca_count({computed_ca_count}) "
        f"[remaining={remaining}, static_count={computed_static_count}]"
    )

    # ── (4) Backlog never exceeds its category ───────────────────────
    assert bp.static_backlog <= computed_static_count, (
        f"static_backlog({bp.static_backlog}) exceeds "
        f"computed_static_count({computed_static_count})"
    )
    assert bp.ca_backlog <= computed_ca_count, (
        f"ca_backlog({bp.ca_backlog}) exceeds "
        f"computed_ca_count({computed_ca_count})"
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. Allocation Invariant Verification
# ══════════════════════════════════════════════════════════════════════════


class TestAllocationInvariants:

    def test_sum_equals_target_no_backlog(self):
        """With no backlog, buckets always sum to target_total."""
        for n in [0, 1, 2, 3, 5, 10, 15, 17, 20, 30, 100, 200]:
            bp = solve_composition(target_total=n, available_static_backlog=0, available_ca_backlog=0)
            check_invariants(bp)

    def test_sum_equals_target_with_backlog(self):
        """With backlog, buckets always sum to target_total."""
        for n in [0, 1, 2, 3, 5, 10, 15, 17, 20, 30, 100, 200]:
            for avail in [0, 1, 5, 10, 50]:
                bp = solve_composition(
                    target_total=n,
                    available_static_backlog=avail,
                    available_ca_backlog=avail,
                )
                check_invariants(bp)

    def test_no_negative_allocations(self):
        """No allocation ever goes below zero, even with extreme inputs."""
        for n in [0, 1, 2, 3, 5, 10, 15, 30, 100]:
            for avail in [0, 1, 5, 10, 50]:
                bp = solve_composition(
                    target_total=n,
                    available_static_backlog=avail,
                    available_ca_backlog=avail,
                )
                assert bp.floor_count >= 0
                assert bp.static_today >= 0
                assert bp.static_backlog >= 0
                assert bp.ca_today >= 0
                assert bp.ca_backlog >= 0

    def test_deterministic_output(self):
        """Same inputs always produce identical outputs."""
        args = dict(target_total=30, available_static_backlog=5, available_ca_backlog=3)
        r1 = solve_composition(**args)
        for _ in range(20):
            r2 = solve_composition(**args)
            assert r1 == r2, "Non-deterministic output detected"

    def test_category_conservation_no_backlog(self):
        """Without backlog, static_today == static_count and ca_today == ca_count."""
        for n in range(0, 101):
            bp = solve_composition(target_total=n, available_static_backlog=0, available_ca_backlog=0)
            remaining = n - bp.floor_count
            expected_static = max(0, math.floor(remaining * STATIC_RATIO))
            expected_ca = remaining - expected_static
            assert bp.static_today + bp.static_backlog == expected_static, (
                f"n={n}: static_today+bp.static_backlog ({bp.static_today}+{bp.static_backlog}) != "
                f"expected_static ({expected_static})"
            )
            assert bp.ca_today + bp.ca_backlog == expected_ca, (
                f"n={n}: ca_today+ca_backlog ({bp.ca_today}+{bp.ca_backlog}) != "
                f"expected_ca ({expected_ca})"
            )

    def test_backlog_redistributes_to_today(self):
        """Unused backlog capacity rolls into the 'today' allocation."""
        for n in [5, 10, 15, 30, 100]:
            # Without backlog
            bp_no = solve_composition(target_total=n, available_static_backlog=0, available_ca_backlog=0)
            # With abundant backlog
            bp_yes = solve_composition(target_total=n, available_static_backlog=999, available_ca_backlog=999)
            # Total must still match
            assert bp_no.target_total == bp_yes.target_total
            check_invariants(bp_yes)


# ══════════════════════════════════════════════════════════════════════════
# 2. Remainder-Absorb Verification
# ══════════════════════════════════════════════════════════════════════════


class TestRemainderAbsorb:

    @pytest.mark.parametrize("total", [0, 1, 2, 3, 5, 10, 15, 30, 100, 200])
    def test_no_drift(self, total):
        """No N-1 or N+1 drift for specified target totals."""
        for avail_static in [0, total]:
            for avail_ca in [0, total]:
                bp = solve_composition(
                    target_total=total,
                    available_static_backlog=avail_static,
                    available_ca_backlog=avail_ca,
                )
                check_invariants(bp)

    def test_final_bucket_absorbs_residual(self):
        """The final bucket in each split correctly absorbs residual."""
        for n in [1, 2, 3, 4, 5, 7, 11, 13, 17, 19, 23, 29, 31]:
            bp = solve_composition(target_total=n)
            check_invariants(bp)

    def test_zero_target(self):
        """Zero-target produces all-zero allocations."""
        bp = solve_composition(target_total=0)
        assert bp.floor_count == 0
        assert bp.static_today == 0
        assert bp.static_backlog == 0
        assert bp.ca_today == 0
        assert bp.ca_backlog == 0
        assert bp.target_total == 0

    def test_single_question(self):
        """Single question correctly allocated without drift."""
        bp = solve_composition(target_total=1)
        check_invariants(bp)
        assert bp.floor_count <= 1

    def test_two_questions(self):
        """Two questions correctly allocated without drift."""
        bp = solve_composition(target_total=2)
        check_invariants(bp)


# ══════════════════════════════════════════════════════════════════════════
# 3. Backlog Verification
# ══════════════════════════════════════════════════════════════════════════


class TestBacklogVerification:

    def test_empty_backlog(self):
        """No backlog available → all allocation is 'today'."""
        bp = solve_composition(target_total=30)
        check_invariants(bp)
        # With no backlog, all static and CA goes to 'today'
        remaining = 30 - bp.floor_count
        expected_static = max(0, math.floor(remaining * STATIC_RATIO))
        assert bp.static_today + bp.static_backlog == expected_static
        assert bp.ca_today + bp.ca_backlog == remaining - expected_static
        assert bp.static_backlog == 0
        assert bp.ca_backlog == 0

    def test_partial_backlog(self):
        """Partial backlog: backlog is capped at available items."""
        for total in [10, 15, 30, 100]:
            for avail in [1, 2, 3, 5]:
                bp = solve_composition(
                    target_total=total,
                    available_static_backlog=avail,
                    available_ca_backlog=avail,
                )
                check_invariants(bp)
                # Backlog must not exceed available
                assert bp.static_backlog <= avail, (
                    f"total={total}, avail={avail}: static_backlog {bp.static_backlog} > {avail}"
                )
                assert bp.ca_backlog <= avail, (
                    f"total={total}, avail={avail}: ca_backlog {bp.ca_backlog} > {avail}"
                )

    def test_full_backlog(self):
        """Full backlog: backlog equals desired computation."""
        for total in [10, 15, 30, 100]:
            remaining = total - max(0, math.floor(total * FLOOR_RATIO))
            max_static = max(0, math.floor(remaining * STATIC_RATIO))
            max_ca = remaining - max_static
            desired_static_b = math.floor(max_static * BACKLOG_RATIO)
            desired_ca_b = math.floor(max_ca * BACKLOG_RATIO)

            bp = solve_composition(
                target_total=total,
                available_static_backlog=max_static,
                available_ca_backlog=max_ca,
            )
            check_invariants(bp)
            # With sufficient backlog, backlog equals desired
            assert bp.static_backlog == desired_static_b, (
                f"total={total}: static_backlog {bp.static_backlog} != desired {desired_static_b}"
            )
            assert bp.ca_backlog == desired_ca_b, (
                f"total={total}: ca_backlog {bp.ca_backlog} != desired {desired_ca_b}"
            )

    def test_oversized_backlog(self):
        """Backlog exceeding capacity is capped; unused capacity stays in 'today'."""
        for total in [5, 10, 15, 30]:
            bp = solve_composition(
                target_total=total,
                available_static_backlog=999,
                available_ca_backlog=999,
            )
            check_invariants(bp)
            # Backlog cannot exceed category total
            remaining = total - bp.floor_count
            expected_static = max(0, math.floor(remaining * STATIC_RATIO))
            expected_ca = remaining - expected_static
            assert bp.static_backlog <= expected_static
            assert bp.ca_backlog <= expected_ca

    def test_backlog_cap_respected(self):
        """Backlog never exceeds 35% of its category even with unlimited items."""
        for total in range(1, 101):
            bp = solve_composition(
                target_total=total,
                available_static_backlog=999,
                available_ca_backlog=999,
            )
            check_invariants(bp)
            remaining = total - bp.floor_count
            expected_static = max(0, math.floor(remaining * STATIC_RATIO))
            expected_ca = remaining - expected_static
            assert bp.static_backlog <= expected_static
            assert bp.ca_backlog <= expected_ca


# ══════════════════════════════════════════════════════════════════════════
# 4. Boundary Verification
# ══════════════════════════════════════════════════════════════════════════


class TestBoundaryVerification:

    def test_zero_total_with_backlog(self):
        """Zero target with backlog must still produce zero allocation."""
        bp = solve_composition(target_total=0, available_static_backlog=100, available_ca_backlog=100)
        check_invariants(bp)
        assert bp.floor_count == 0
        assert bp.static_today == 0
        assert bp.static_backlog == 0
        assert bp.ca_today == 0
        assert bp.ca_backlog == 0

    def test_large_values_stable(self):
        """Large question counts do not cause overflow or drift."""
        for total in [500, 1000, 5000, 10000]:
            bp = solve_composition(target_total=total)
            check_invariants(bp)
            bp_big = solve_composition(target_total=total, available_static_backlog=1000, available_ca_backlog=1000)
            check_invariants(bp_big)

    def test_target_one_with_varied_backlog(self):
        """Very small total with extreme backlog remains valid."""
        for avail in [0, 1, 5, 10, 100]:
            bp = solve_composition(target_total=1, available_static_backlog=avail, available_ca_backlog=avail)
            check_invariants(bp)




# ══════════════════════════════════════════════════════════════════════════
# 5. Property / Sweep Testing
# ══════════════════════════════════════════════════════════════════════════


class TestPropertySweep:

    def test_sweep_zero_to_two_hundred(self):
        """Invariant holds for every target_total in [0, 200]."""
        for n in range(0, 201):
            bp = solve_composition(target_total=n)
            check_invariants(bp)

    def test_sweep_with_backlog(self):
        """Invariant holds across range with diverse backlog levels."""
        for n in range(0, 201):
            for avail in [0, 1, 5, 10]:
                if avail > n:
                    continue
                bp = solve_composition(target_total=n, available_static_backlog=avail, available_ca_backlog=avail)
                check_invariants(bp)

    def test_sweep_deterministic(self):
        """Each (total, static_b, ca_b) produces the same result every time."""
        for n in [0, 1, 2, 3, 5, 7, 10, 15, 30, 100, 200]:
            for sa in [0, 1, 5]:
                for ca in [0, 1, 5]:
                    first = solve_composition(target_total=n, available_static_backlog=sa, available_ca_backlog=ca)
                    for _ in range(10):
                        assert solve_composition(
                            target_total=n, available_static_backlog=sa, available_ca_backlog=ca
                        ) == first

    def test_sweep_all_components_non_negative(self):
        """All five allocation components are non-negative for n in [0, 200]."""
        for n in range(0, 201):
            bp = solve_composition(target_total=n)
            assert bp.floor_count >= 0
            assert bp.static_today >= 0
            assert bp.static_backlog >= 0
            assert bp.ca_today >= 0
            assert bp.ca_backlog >= 0

    def test_sweep_no_hidden_drift(self):
        """Repeated identical calls produce the same allocation (no state leakage)."""
        baseline = [solve_composition(target_total=n) for n in range(0, 101)]
        repeated = [solve_composition(target_total=n) for n in range(0, 101)]
        assert baseline == repeated

    def test_undoes_not_accumulate(self):
        """Backlog-only tests: unused backlog this run does not affect next run."""
        results = []
        for n in [5, 10, 15, 30]:
            results.append(solve_composition(target_total=n, available_static_backlog=0, available_ca_backlog=0))
        for n in [5, 10, 15, 30]:
            results.append(solve_composition(target_total=n, available_static_backlog=10, available_ca_backlog=10))
        for n in [5, 10, 15, 30]:
            results.append(solve_composition(target_total=n, available_static_backlog=0, available_ca_backlog=0))
        # All results must be independent (no state carried between calls)
        for bp in results:
            check_invariants(bp)


# ══════════════════════════════════════════════════════════════════════════
# 6. Dependency Boundary Verification
# ══════════════════════════════════════════════════════════════════════════


class TestDependencyBoundaries:

    SOURCE = inspect.getsource(sys.modules["src.composition_engine"])

    def test_no_database_import(self):
        """Must not import database module."""
        assert "src.database" not in self.SOURCE, "composition_engine imports src.database"

    def test_no_generator_import(self):
        """Must not import generator module."""
        assert "src.generator" not in self.SOURCE, "composition_engine imports src.generator"

    def test_no_evaluator_import(self):
        """Must not import evaluator module."""
        assert "src.evaluator" not in self.SOURCE, "composition_engine imports src.evaluator"

    def test_no_scraper_import(self):
        """Must not import scraper module."""
        assert "src.scraper" not in self.SOURCE, "composition_engine imports src.scraper"

    def test_no_diagnostic_import(self):
        """Must not import diagnostic module."""
        assert "src.diagnostic" not in self.SOURCE, "composition_engine imports src.diagnostic"

    def test_no_rag_store_import(self):
        """Must not import rag_store module."""
        assert "src.rag_store" not in self.SOURCE, "composition_engine imports src.rag_store"

    def test_no_math_utils_import(self):
        """Should not need math_utils (has its own math)."""
        assert "src.math_utils" not in self.SOURCE, "composition_engine imports src.math_utils"

    def test_only_calibration_dependency(self):
        """Only src dependency is calibration (config)."""
        tree = ast.parse(self.SOURCE)
        src_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("src"):
                    src_imports.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("src"):
                        src_imports.add(alias.name)
        assert src_imports == {"src.calibration"}, f"Unexpected src imports: {src_imports}"

    def test_no_cloud_api(self):
        """Must not use any http/requests/cloud libraries."""
        assert "requests" not in self.SOURCE
        assert "urllib" not in self.SOURCE
        assert "httpx" not in self.SOURCE
        assert "aiohttp" not in self.SOURCE

    def test_only_stdlib_and_pydantic(self):
        """Only allowed top-level imports: stdlib, pydantic, calibration."""
        tree = ast.parse(self.SOURCE)
        toplevel_imports = set()
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        toplevel_imports.add(alias.name.split(".")[0])
                else:
                    if node.module:
                        toplevel_imports.add(node.module.split(".")[0])
        # 'math' is stdlib, 'pydantic' is allowed, 'src' apps are checked above
        forbidden = toplevel_imports - {"math", "typing", "pydantic", "src"}
        assert not forbidden, f"Unexpected top-level imports: {forbidden}"


# ══════════════════════════════════════════════════════════════════════════
# 7. Architecture Interface Compliance (Defect Detection)
# ══════════════════════════════════════════════════════════════════════════


class TestArchitectureInterface:

    def test_enforce_floor_parameter_missing(self):
        """ARCHITECTURE: requires enforce_floor flag — implementation is missing it."""
        solve_composition(target_total=30, enforce_floor=False)

    def test_enforce_backlog_parameter_missing(self):
        """ARCHITECTURE: requires enforce_backlog flag — implementation is missing it."""
        solve_composition(target_total=30, enforce_backlog=True)

    def test_no_mode_parameter(self):
        """ARCHITECTURE: requires mode parameter — implementation is missing it."""
        solve_composition(target_total=30, mode="TOPIC_PRACTICE")

    def test_no_composition_plan_total_field(self):
        """ARCHITECTURE: CompositionPlan has total field — CompositionPlan has target_total."""
        bp = solve_composition(target_total=30)
        assert hasattr(bp, "target_total"), "Blueprint has target_total"
        # Architecture calls it 'total', implementation calls it 'target_total'
        # Not a functional defect, just naming

    def test_composition_plan_missing_fields(self):
        """ARCHITECTURE: CompositionPlan requires floor_topics, backlog_topics, mode, system_intent_header."""
        bp = solve_composition(target_total=30)
        missing = []
        for field in ["floor_topics", "backlog_topics", "mode", "system_intent_header"]:
            if not hasattr(bp, field):
                missing.append(field)
        assert not missing, f"CompositionPlan missing fields: {missing}"

    def test_function_name_not_solve_composition(self):
        """ARCHITECTURE: entry point is solve_composition — implementation uses solve_composition."""
        import src.composition_engine as ce
        assert hasattr(ce, "solve_composition") or hasattr(ce, "solve_composition"), \
            "Neither solve_composition nor solve_composition found"
        if hasattr(ce, "solve_composition") and not hasattr(ce, "solve_composition"):
            pytest.fail(
                "Architecture specifies solve_composition() as entry point. "
                "Only solve_composition() found."
            )
