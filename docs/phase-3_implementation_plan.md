# Phase 3 Implementation Plan: Intelligence Core

## Section 1: Phase 3 Understanding

Phase 3 is the highest-complexity phase of the orchestrator. It introduces the `composition_engine.py` constraint solver, the async `generator.py` with its Critic Agent loop, and the adversarial `evaluator.py`. After this phase, the system is capable of producing complete, adaptive 30-question papers and grading subjective answers without needing the API server.

---

## Section 2: Implementation Groups

### Group 1: The Composition Engine

#### Files In Scope
* `src/composition_engine.py`

#### Responsibilities
* Implement the pure-logic constraint solver for the test blueprint.
* Execute the 4-step allocation pipeline: 
  1. Floor Guarantee (random syllabus, overlap allowed).
  2. Recalculate remaining quota dynamically.
  3. Content Type Split (static vs. CA).
  4. Backlog Rule (within category, using `source_type`).
* Ensure remainder-absorb rounding (final bucket absorbs difference) to guarantee the invariant `sum = target_questions`.
* Support dynamic parameters: topic selection (A1), custom question counts (A2), and dynamic timing (A4).

#### Dependencies Required Before Starting
* Phase 1 schemas and calibration configurations.

#### Constraints
* **Pure Logic Only:** No database reads/writes. No Cloud API dependencies.
* **No Generator Coupling:** Must not import `generator.py` or depend on its runtime state.

#### Verification Gate
* **Test File:** `tests/test_composition_engine.py`
* **Expected behaviors (Invariants):**
  * **Total Match:** Final allocations must always sum precisely to the target question count.
  * **Non-Negative:** Allocations must never fall below zero under any constraints.
  * **Deterministic Output:** Identical student states must yield identical blueprint allocations.
  * **Backlog Stability:** Injecting backlog constraints must purely redistribute the internal category splits, never altering the final target total.
  * Remainder-absorb rounding prevents assertion failures on edge cases.

#### Exit Criteria
* All tests pass. 100% mathematical certainty that allocations sum to target.

#### Risks
* Floating point truncation resulting in N-1 or N+1 question allocations.

---

### Group 2: The Generator

#### Files In Scope
* `src/generator.py`

#### Responsibilities (Internal Pipeline Stages)
1. **State Retrieval**: Read student context (`student_profile`, `topic_progress`, `backlog_queue`, etc.).
2. **Composition Request**: Request an adaptive blueprint from `composition_engine.py`.
3. **RAG Retrieval**: Retrieve context chunks from `rag_store.py` (syllabus, PYQs).
4. **Cloud Generation**: Execute the Async Cloud API generation loop.
5. **Critic Retry Handling**: Execute scoring loop (Gates 1 & 2).
   * **Limits:** Maximum 3 retries per question.
   * **Timeout:** Implement strict timeouts to prevent hanging threads.
   * **Partial Failure:** If a subset of questions fail, do not abort the entire batch; only replace the failed ones via fallback.
6. **Fallback Activation**: Route exhausted/failed questions to `static_assets/pyq/` flat JSON pool.
7. **Database Persistence**: Write final questions to `question_bank` with `provenance_tags` and return the System Intent Header string.

#### Dependencies Required Before Starting
* Group 1 (`composition_engine.py`).
* Phase 1 DB, schemas, and `math_utils.py`.
* Phase 2 `rag_store.py` and `scraper.py` (data structures).

#### Constraints
* **No Inline Math:** Must call `math_utils.py` for any Elo computations; no inline formulas (Constraint C-05).
* **No Evaluation Coupling:** Must not import `evaluator.py`.
* **Graceful Degradation:** Must not hard-crash on malformed Cloud API JSON or empty `pyq_collection`.

#### Verification Gate
* **Test File:** `tests/test_generator.py`
* **Expected behaviors:**
  * Critic Agent triggers regenerate on scores < 0.85.
  * Retry exhaustion correctly pulls from the static JSON pool.
  * All generated questions are safely committed to `question_bank`.

#### Exit Criteria
* Generator successfully produces exactly 30 questions under mocked API conditions and handles failure states without corrupting the DB.

#### Risks
* Async worker exhaustion or rate-limit violations against the Cloud API.
* Infinite generation loops if retry limits are not strictly enforced.

---

### Group 3: The Evaluator

#### Files In Scope
* `src/evaluator.py`

#### Responsibilities
* Receive `student_response`, durations, and confidence levels.
* Retrieve the `blueprint` from `question_bank` (or accept it directly via parameter).
* Execute Pass 1: Blueprint Mapping (structural completeness).
* Execute Pass 2: Adversarial Cross-Examination (analytical quality).
* Normalize the final subjective score to `0.0-1.0` (Constraint C-01).
* Store the detailed raw feedback in `detailed_evaluation` JSON.
* Write the result to `attempt_history`.

#### Dependencies Required Before Starting
* Phase 1 DB, schemas, and calibration configuration.
* Cloud API.

#### Constraints
* **Strict Blueprint Resolution:** 
  * If `question_id` is provided, the Evaluator MUST fetch the blueprint from the database (Database-driven path).
  * If `question_id` is None, the `blueprint` dictionary MUST be provided explicitly (Benchmark-driven path).
  * Passing both or neither must instantly raise an `EvaluationFailure` exception to prevent architectural drift.
* **Forbidden Imports:** Must NOT import `generator.py` or `rag_store.py`.

#### Verification Gate
* **Test File:** `tests/test_evaluator.py`
* **Expected behaviors:**
  * Score normalization strictly guarantees output between 0.0 and 1.0.
  * Missing both `question_id` and `blueprint` raises a critical exception.
  * Pass 1 output successfully feeds into Pass 2 context.

#### Exit Criteria
* Evaluator accurately persists evaluation history and supports benchmark injection perfectly.

#### Risks
* Pass 1 failure completely breaks Pass 2 if context is not chained correctly.
* Safe mode PYQ blueprint mismatches degrading evaluation accuracy.

---

### Group 4: Phase 3 Verification (Integration)

#### Files In Scope
* `tests/test_phase3_integration.py`

#### Responsibilities
* Verify End-to-End question generation and subsequent evaluation.
* Guarantee that Phase 1 and Phase 2 architectures remain immutable.
* Prove boundary isolation (Generator vs Evaluator).

#### Dependencies Required Before Starting
* Groups 1, 2, and 3 complete.

#### Constraints
* **Use mocked endpoints:** Must use only mocked Cloud APIs.
* **Disposable Databases:** Integration tests must use temporary, isolated in-memory or file-based databases rather than requiring universal transaction rollbacks, ensuring modules that intentionally commit state can be tested realistically.

#### Verification Gate
* Integration suite runs zero regressions against Phase 1 constraints while executing Phase 3 components in sequence.

#### Exit Criteria
* 100% test pass rate relying solely on behavior-driven verification gates.

#### Risks
* State leakage across test runs due to async generator threads overlapping in SQLite memory pools.
