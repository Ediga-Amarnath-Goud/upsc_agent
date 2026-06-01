# Phase 1: Foundation — Implementation Specification

**Objective:** Define the boundaries, responsibilities, and constraints for every file in Phase 1 before any code is generated. This ensures modularity, prevents scope creep, and minimizes rewrite risk.

---

## 1. `calibration_config.yaml`

### File Objective
Centralize all system hyperparameters, tuning weights, mode rules, and thresholds into a single source of truth.

### Responsibilities
* **Belongs here:** Hardcoded constants, Elo thresholds, timing limits, decay rates, practice mode definitions (A3), composition ratios (A2).
* **Does NOT belong here:** Environment variables (e.g., API keys, host/port). 

### Inputs
* Manual edits by the administrator on the local disk.

### Outputs
* A structured YAML file.

### Dependencies
* **Internal:** None.
* **External:** None.
* **Future:** Read by `calibration.py`.

### Constraints
* **Architectural:** Must contain all fields required by Add-Ons A1-A7 and Contradiction fixes C-01-C-13.
* **Local-first:** Resides entirely on the local filesystem.

### Failure Conditions
* **Expected:** Malformed YAML syntax.
* **Edge cases:** Missing keys, type mismatches (e.g., string instead of int).

### Verification Criteria
* **Runtime:** Parses successfully as valid YAML.

### Coupling Analysis
* **Depends on:** Nothing.
* **Depended on by:** Tightly coupled to `calibration.py` which expects exact keys.
* **Rewrite Risk:** LOW (schema might expand, but existing keys won't change fundamentally).

### Implementation Complexity
LOW

---

## 2. `calibration.py`

### File Objective
Provide strongly-typed, cached, runtime access to the `calibration_config.yaml` file.

### Responsibilities
* **Belongs here:** YAML parsing, caching the configuration object, reloading logic.
* **Does NOT belong here:** Business logic, math equations.

### Inputs
* `calibration_config.yaml` file from disk.

### Outputs
* `get_config()` function returning a singleton typed configuration object (e.g., using Pydantic `BaseModel`).
* `reload_config()` function to invalidate the cache.

### Dependencies
* **Internal:** `exceptions.py` (raises `CalibrationFailure`), `calibration_config.yaml`.
* **External:** `pyyaml`, `pydantic`.

### Constraints
* **Performance:** Must cache the configuration after first load. File I/O should only happen on startup or explicit reload.
* **Validation:** Must validate the structure of the parsed YAML against expected schema.

### Failure Conditions
* **Expected:** File not found, parsing failure, schema validation failure.
* **Invalid states:** Attempting to read a missing key.

### Verification Criteria
* **Import checks:** Successfully imports.
* **Unit tests:** Loading a valid mock YAML succeeds. Loading an invalid/missing YAML raises `CalibrationFailure`.

### Coupling Analysis
* **Depends on:** `calibration_config.yaml`.
* **Depended on by:** Almost every module in the project.
* **Rewrite Risk:** HIGH if the YAML schema changes, as the Python Pydantic models must be updated to match.

### Implementation Complexity
LOW

---

## 3. `models.py`

### File Objective
Define the persistent data structures (database schema) using SQLAlchemy ORM.

### Responsibilities
* **Belongs here:** SQLAlchemy declarative Base, table definitions (all 10 tables including `test_sessions`), column types, relationships.
* **Does NOT belong here:** Database connection logic, session management, query execution.

### Inputs
* None.

### Outputs
* SQLAlchemy ORM classes (`StudentProfile`, `TestSession`, `QuestionBank`, etc.).

### Dependencies
* **Internal:** None.
* **External:** `sqlalchemy`.

### Constraints
* **Architectural:** Must align perfectly with the frozen architecture (R3: `test_sessions` must have `student_id` and `subject_code`).
* **SQLite specific:** SQLite lacks native Array/JSON types; must use `JSON` or `Text` for list fields.

### Failure Conditions
* **Invalid states:** Conflicting column definitions, invalid foreign key relationships.

### Verification Criteria
* **Import checks:** File imports without error.
* **Runtime:** Alembic/SQLAlchemy can successfully parse the metadata to generate the schema.

### Coupling Analysis
* **Depends on:** Nothing.
* **Depended on by:** `database.py`, and later all spoke modules (`generator.py`, `evaluator.py`, etc.) for querying.
* **Rewrite Risk:** MEDIUM. Adding columns later is easy, but changing primary keys or relationships causes migration pain.

### Implementation Complexity
MEDIUM

---

## 4. `database.py`

### File Objective
Manage database connections, session lifecycle, and schema initialization.

### Responsibilities
* **Belongs here:** SQLAlchemy engine creation, sessionmaker factory, `init_db()`, `expire_stale_sessions()` utility.
* **Does NOT belong here:** Table definitions, business logic queries.

### Inputs
* `DATABASE_URL` environment variable.
* ORM models from `models.py`.

### Outputs
* `get_session()` context manager/dependency.
* `init_db()` function.

### Constraints
* **Performance:** Must use connection pooling. SQLite requires `check_same_thread=False` for FastAPI. SQLite WAL (Write-Ahead Logging) mode is highly recommended for concurrency.

### Failure Conditions
* **Expected:** Database file locked, disk full, missing parent directory.

### Verification Criteria
* **Integration expectations:** Calling `init_db()` physically creates `hub_database.db` and all 10 tables on disk.

### Coupling Analysis
* **Depends on:** `models.py`.
* **Depended on by:** `main.py`, `rag_store.py`, `generator.py` (via `get_session()`).
* **Rewrite Risk:** LOW. Standard SQLAlchemy boilerplate.

### Implementation Complexity
LOW

---

## 5. `schemas.py`

### File Objective
Define strict data validation contracts (Pydantic models) for API boundaries and LLM structured outputs.

### Responsibilities
* **Belongs here:** Request/response payloads (`TestRequestSchema`, `SubmitAnswerResponseSchema`), LLM schemas (`GeneratedQuestionSchema`, `CriticEvaluationSchema`, `SafeModePYQSchema`).
* **Does NOT belong here:** ORM database models, business logic.

### Inputs
* Raw JSON or dictionaries from HTTP requests or LLM outputs.

### Outputs
* Validated, strongly-typed Pydantic model instances.

### Dependencies
* **External:** `pydantic`.

### Constraints
* **Validation:** Every field must have strict typing.
* **LLM compatibility:** Every `Field()` must include a clear `description=` so the Cloud LLM understands the output constraint.

### Failure Conditions
* **Expected:** Validation errors on missing fields or incorrect types.

### Verification Criteria
* **Unit tests:** Passing valid dictionaries successfully creates models. Passing invalid dictionaries raises `ValidationError`.

### Coupling Analysis
* **Depends on:** Nothing.
* **Depended on by:** API routes (`main.py`) and Cloud logic (`generator.py`, `evaluator.py`).
* **Rewrite Risk:** LOW. Safely extensible.

### Implementation Complexity
LOW

---

## 6. `math_utils.py`

### File Objective
Centralize all system mathematics (Elo computation, Certainty-Weighted Performance, Memory Decay, Dynamic Timing) to ensure purity and testability.

### Responsibilities
* **Belongs here:** Pure mathematical functions.
* **Does NOT belong here:** Database queries, API calls, side-effects.

### Inputs
* Primitive types (floats, ints) and configuration parameters.

### Outputs
* Computed primitive values.

### Constraints
* **Validation:** Bounds must be strictly clamped (e.g., Elo cannot exceed ceiling, `P_w` cannot be negative).

### Failure Conditions
* **Edge cases:** Division by zero (e.g., zero time elapsed), negative inputs.

### Verification Criteria
* **Unit tests:** Must have near 100% test coverage. Every mathematical edge case, zero, negative, and extreme bound must be proven.

### Coupling Analysis
* **Depends on:** Nothing (can take config values as arguments to remain pure).
* **Depended on by:** `composition_engine.py`, `generator.py`, `main.py`.
* **Rewrite Risk:** LOW. Formulas are mathematically frozen.

### Implementation Complexity
MEDIUM

### Implemented Formulas (Group 3)
* **`compute_difficulty_to_elo(difficulty_tier: int) -> int`**:
  * `tier × 100 + 1000`, tier clamped `[1, 10]`.
* **`compute_expected_elo(r_old: int, r_question: int) -> float`**:
  * `1.0 / (1.0 + 10^((r_question - r_old) / 400.0))`. Protected against `OverflowError`.
* **`compute_elo_update(r_old, k_factor, p_w, expected, floor, ceiling) -> int`**:
  * `R_new = R_old + K × (P_w - expected)`. Output clamped strictly to `[floor, ceiling]`.
* **`compute_certainty_weighted_performance(accuracy, confidence, duration, expected_sec, pacing_max) -> float`**:
  * `P_w = accuracy × confidence_weight × (1.0 - (|duration - expected_sec| / pacing_max))`. Clamped `[0.0, 1.0]`.
* **`compute_memory_decay_interval(i_base, alpha, confidence, difficulty, weight_scaler, mistakes) -> float`**:
  * `D_t = (difficulty × weight_scaler) + (mistakes × 0.1)`. 
  * `I_next = I_base × exp(alpha × confidence × (2.0 - D_t))`. Clamped `[1.0, 30.0]` days, exponent clamped `[-20.0, 20.0]` for overflow protection.
* **`update_stability_index(i_base, i_next) -> float`**:
  * `(0.9 × i_base) + (0.1 × i_next)`.
* **`compute_recovery_velocity(delta_elo, delta_days) -> float`**:
  * `delta_elo / max(1.0, delta_days)`. Floor of 1.0 day applied as per C-12 architecture rule.
* **`compute_dynamic_time_limit(question_count, expected_seconds) -> int`**:
  * `count × expected_seconds`.

---

## 7. `unit tests` (Phase 1)

### File Objective
Mathematically and structurally prove that Phase 1 foundation code functions correctly in strict isolation.

### Responsibilities
* **Belongs here:** Tests for YAML parsing, DB initialization, schema validation, and math edge cases.
* **Does NOT belong here:** Cloud API mocks (that's Phase 3), real DB integration across modules.

### Inputs
* Phase 1 code.

### Outputs
* Test pass/fail suite.

### Constraints
* **Performance:** Suite must run in under 2 seconds. In-memory SQLite (`sqlite:///:memory:`) should be used for DB tests.

### Verification Criteria
* `pytest` exits with code 0.

---

# Recommended Implementation Groups

To minimize rewrite risk and ensure sequential stability, I recommend breaking Phase 1 into three coding groups.

### Group 1: The Contracts
* **Files:** `calibration_config.yaml`, `schemas.py`, `test_schemas.py`
* **Reason:** These define the static contracts (config fields and data payloads) that everything else will use. They depend on absolutely nothing.
* **Verification Gate:** MUST pass YAML syntax check and `pytest tests/test_schemas.py` before proceeding to Group 2.

### Group 2: The Data Layer
* **Files:** `models.py`, `database.py`, `test_database.py`
* **Reason:** Stable persistence infrastructure reduces downstream integration issues. `models.py` defines the schema, `database.py` spins up the engine.
* **Verification Gate:** MUST pass `pytest tests/test_database.py` to confirm table generation works perfectly before proceeding to Group 3.

### Group 3: The Logic Engine
* **Files:** `calibration.py`, `math_utils.py`, `test_calibration.py`, `test_math_utils.py`
* **Reason:** `calibration.py` makes Group 1's YAML usable in Python. `math_utils.py` is explicitly frozen as a 100% pure math module (constants passed as params, no config imports). Testing these together ensures the pure logic is sound before tying into the database.
* **Verification Gate:** MUST pass `pytest` on both test files to prove mathematical edge cases and config caching.

---
**Status:** Group 1 execution complete. Awaiting confirmation before beginning code generation for Group 2.
