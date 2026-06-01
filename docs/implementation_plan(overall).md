# UPSC Adaptive AI Orchestrator — Implementation Plan

**Blueprint Status:** FROZEN — All design decisions finalized  
**Date:** 2026-06-01  
**Source Documents:**  
- [UPSC_Orchestrator_Master_Documentation.md](file:///c:/Users/amarn/Desktop/upsc_agent/UPSC_Orchestrator_Master_Documentation.md) — Architecture reference  
- [UPSC_Implementation_Roadmap.md](file:///c:/Users/amarn/Desktop/upsc_agent/UPSC_Implementation_Roadmap.md) — Phase definitions + contradiction audit  

---

## Frozen Design Decisions (Q1–Q5)

These are locked. No further discussion required.

| Question | Decision | Key Addition |
|----------|----------|--------------|
| Q1 — PYQ Format | `SafeModePYQSchema` with `subject_id` + `source_year` | New schema in `schemas.py` |
| Q2 — Topper Blueprint | Dynamic Cloud API generation + local cache (`essay_XX.blueprint.json`) | Caching logic in `benchmark_runner.py` |
| Q3 — Pacing Drift | Return `psychological_drift_warning: bool` + `warning_reason: str` | Response payload change in `main.py` |
| Q4 — Session Lifecycle | Scoped to test batch, 2h inactivity timeout, no explicit close | Timeout check in `/submit-answer` |
| Q5 — Document Ingestor | `POST /ingest-document` endpoint | New route in `main.py` |

---

## Pre-Freeze Refinements Applied

5 refinements applied before final freeze. These are structural improvements that reduce rewrite risk.

| # | Refinement | Impact |
|---|-----------|--------|
| R1 | **`composition_engine.py` moved to Phase 3** | Built once, correctly, alongside generator.py. Eliminates the Phase 3 → Phase 5 rewrite cycle. |
| R2 | **Safe mode freshness aligned to 48h** | `health_check()` now uses `config.current_affairs_filters.rolling_window_hours` (48h) instead of hardcoded 24h. Matches the scraper's rolling window. More resilient to temporary scraper failures. |
| R3 | **`test_sessions` fields renamed** | `subject_id` → `subject_code`. Added `student_id` (defaults to `'default'` for V1 single-user). Removes ambiguity with `student_profile.subject_id` FK semantics. |
| R4 | **Remainder-absorb rounding** | Final bucket in every composition split absorbs `total - sum(all_other_buckets)` instead of independently rounding. Guarantees invariant without assertion failures. |
| R5 | **`diagnostic.py` moved to end of Phase 2** | Student calibration happens before the intelligence core is built. Elo data is available for Phase 3 testing with real adaptive behavior. |

---

## Add-Ons Integrated

7 add-ons accepted. Placed at recommended phases to avoid architectural disruption.

| Add-On | Description | Priority | Phase |
|--------|-------------|----------|-------|
| A1 — Dynamic Topic-Based Generation | User selects subject/topics/count/mode | HIGH | 3 |
| A2 — Dynamic Question Counts | Percentage-based allocation instead of fixed 30 | HIGH | 3 |
| A3 — Multiple Practice Modes | DAILY_SPRINT, TOPIC_PRACTICE, REVISION_MODE, MOCK_TEST | HIGH | 2 |
| A4 — Dynamic Timing | `time = question_count × expected_seconds` | MEDIUM | 3 |
| A5 — Frontend-Controlled Inputs | Frontend: selection UI. Backend: composition logic | HIGH | 4 |
| A6 — Session-Scoped Study Intent | `today_focus` with soft weighting boost | MEDIUM | 2 |
| A7 — Constraint-Based Composition Engine | Replace fixed composition with constraint solver | HIGH | 3 (R1) |

---

## Impact Analysis: What Changes From Original Architecture

> [!IMPORTANT]
> The add-ons do NOT change the Hub-and-Spoke architecture, the database schema fundamentals, or the mathematical models. They extend the **composition pipeline** and **API contracts**.

### Files Modified Beyond Original Spec

| File | Original Scope | Add-On Changes |
|------|---------------|----------------|
| `calibration_config.yaml` | Fixed params | Add `practice_modes` block, `session.inactivity_timeout_minutes` |
| `models.py` | 9 tables | Add `practice_mode` + `study_context` to `daily_study_log`. New `test_sessions` table with `student_id` + `subject_code` (R3) |
| `schemas.py` | 5 schemas | Add `SafeModePYQSchema`, `TestRequestSchema`, `SubmitAnswerResponseSchema` |
| `generator.py` | Fixed 30-question pipeline | Delegates composition to `composition_engine.py`. Accepts variable inputs. |
| `main.py` | 5 routes | Add `/ingest-document`. Modify `/generate-test` to accept extended request body |

### New Files

| File | Phase | Purpose |
|------|-------|---------|
| `composition_engine.py` | 3 (R1) | Constraint solver. Pure logic, no Cloud/DB. Imported by generator.py. |

---

## Directory Structure (Updated)

```
upsc_agent/
├── UPSC_Agent_Data/
│   ├── hub_database.db
│   ├── vector_store/
│   │   ├── syllabus_collection/
│   │   └── pyq_collection/
│   ├── static_assets/
│   │   ├── pyq/
│   │   │   ├── prelims/              ← JSON files, SafeModePYQSchema format
│   │   │   └── mains/
│   │   └── topper_copies/
│   │       ├── essay_01.txt
│   │       ├── essay_01.blueprint.json   ← NEW: cached blueprint (Q2)
│   │       └── ...
│   ├── exports/
│   └── archive/
├── src/
│   ├── calibration_config.yaml
│   ├── calibration.py
│   ├── models.py
│   ├── database.py
│   ├── schemas.py
│   ├── math_utils.py
│   ├── rag_store.py
│   ├── scraper.py
│   ├── composition_engine.py          ← NEW (Phase 3 — R1)
│   ├── generator.py
│   ├── evaluator.py
│   ├── diagnostic.py
│   ├── pdf_exporter.py
│   ├── safe_mode.py
│   ├── main.py
│   └── benchmark_runner.py
├── tests/
│   ├── test_math_utils.py
│   ├── test_calibration.py
│   ├── test_schemas.py
│   ├── test_database.py
│   ├── test_composition_engine.py
│   └── ...
└── requirements.txt
```

---

# Phase 1 — Foundation

> [!NOTE]
> Phase 1 is unchanged from the original architecture. The add-ons require no Phase 1 modifications. Build order follows user's recommendation.

## Build Order

```
1. calibration_config.yaml
2. calibration.py
3. models.py
4. database.py
5. schemas.py
6. math_utils.py
7. Unit tests for Phase 1
```

---

### 1.1 `calibration_config.yaml`

#### [NEW] `src/calibration_config.yaml`

Complete config with all audit additions (C-02, C-13) + add-on support blocks:

```yaml
elo_system:
  k_factor: 32
  base_rating: 1200
  floor_rating: 800
  ceiling_rating: 2000                    # C-13

test_pacing:                              # C-02
  prelims_expected_seconds_per_question: 60
  mains_expected_seconds_per_question: 450
  csat_expected_seconds_per_question: 60

certainty_weights:
  high: 1.0
  medium: 0.75
  low: 0.5
  pacing_max_seconds: 120

current_affairs_filters:
  similarity_threshold: 0.88
  rolling_window_hours: 48
  min_source_consensus: 2

memory_decay:
  alpha_multiplier: 1.0
  base_revision_interval_days: 3.0
  difficulty_weight_scaler: 0.15

curricular_floor:
  random_syllabus_allocation: 0.20

composition:                              # A2: percentage-based
  static_ratio: 0.60
  ca_ratio: 0.40
  backlog_ratio: 0.35

behavioral_fatigue_limits:
  pacing_std_dev_threshold: 0.40
  streak_decay_trigger: 3

critic_thresholds:
  fact_check_verification: 0.85
  semantic_authenticity: 0.75
  distractor_plausibility: 0.75
  blueprint_alignment: 0.70
  combined_minimum: 0.85

diagnostic:
  questions_per_subject: 5
  exceptional_threshold: 0.85
  exceptional_elo: 1450
  average_elo: 1200
  growth_elo: 950
  average_threshold: 0.50

scraper:
  daily_run_hour: 6
  daily_run_minute: 0
  archival_hot_days: 30
  archival_warm_days: 90

pdf:
  watermark_text: "THE FELLOW ASPIRANT"
  watermark_font_size: 52
  watermark_opacity: 0.15
  watermark_rotation: 45
  bottom_buffer: 120
  mains_blank_space: 90

session:                                  # Q4
  inactivity_timeout_minutes: 120

practice_modes:                           # A3: mode definitions
  DAILY_SPRINT:
    default_question_count: 30
    enforce_backlog: true
    enforce_floor: true
    time_limit_enabled: true
  TOPIC_PRACTICE:
    default_question_count: 20
    enforce_backlog: false
    enforce_floor: false
    time_limit_enabled: true
  REVISION_MODE:
    default_question_count: 15
    enforce_backlog: true
    enforce_floor: false
    time_limit_enabled: false
  MOCK_TEST:
    default_question_count: 100
    enforce_backlog: false
    enforce_floor: true
    time_limit_enabled: true
```

---

### 1.2 `calibration.py`

#### [NEW] `src/calibration.py`

- Parses YAML on first import, caches result in memory
- `get_config()` → returns cached `CalibrationConfig` singleton
- `reload_config()` → force fresh parse, invalidates cache
- All spokes import from this module, never raw YAML
- Raises `CalibrationFailure` if file missing or malformed

---

### 1.3 `models.py`

#### [NEW] `src/models.py`

All 9 original tables + audit additions + add-on columns + `test_sessions`:

**Tables:**

| Table | Key Changes from Original |
|-------|--------------------------|
| `student_profile` | + `baseline_elo_rating`, `recovery_velocity_score`, `consecutive_stable_attempts` (C-11) |
| `topic_progress` | New table as specified |
| `daily_study_log` | + `practice_mode` (A3), `study_context` (A6) |
| `backlog_queue` | + `source_type` (C-09) |
| `current_affairs_feed` | No changes |
| `question_bank` | + `provenance_tags`, `generation_time_ms`, `tokens_consumed`, `critic_retry_count` |
| `attempt_history` | + `session_id`, `confidence_level`, `response_duration_seconds` |
| `experiment_runs` | No changes |
| `manual_overrides` | No changes |
| `test_sessions` (**NEW**) | See below |

**New table `test_sessions` (R3 — renamed fields):**

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `session_id` | Text | — | Primary Key (UUID) |
| `student_id` | Text | `'default'` | **R3**: Separate from subject. V1 single-user defaults to `'default'`. Multi-user ready. |
| `subject_code` | Text | — | **R3**: Renamed from `subject_id`. Unambiguous reference to target subject. FK → `student_profile.subject_id` at application level, not DB constraint (different naming). |
| `test_type` | Text | — | `'PRELIMS_GS'`, `'CSAT'`, `'MAINS_SUBJECTIVE'` |
| `practice_mode` | Text | `'DAILY_SPRINT'` | A3: mode enum |
| `study_context` | Text | NULL | A6: JSON, e.g. `{"today_focus":"POLITY"}` |
| `topics_requested` | Text | NULL | A1: JSON array of topic strings |
| `question_count` | Integer | 30 | A2: dynamic count |
| `composition_summary` | Text | NULL | System Intent Header string |
| `session_started_at` | Timestamp | — | Creation time |
| `last_activity_at` | Timestamp | — | Updated on each `/submit-answer` |
| `session_status` | Text | `'ACTIVE'` | `'ACTIVE'`, `'COMPLETED'`, `'EXPIRED'` |

**Custom Exception Classes** (defined in `exceptions.py`):
- `GenerationFailure`
- `EvaluationFailure`
- `CalibrationFailure`
- `CurrentAffairsFailure`
- `RAGFailure`
- `UserBehaviorFlag`

---

### 1.4 `database.py`

#### [NEW] `src/database.py`

- SQLAlchemy engine → `UPSC_Agent_Data/hub_database.db`
- Auto-creates directory if not exists
- `init_db()` — idempotent, creates all tables (now 10 including `test_sessions`)
- Context-managed `get_session()` generator
- Session expiry helper: `expire_stale_sessions(timeout_minutes=120)` — marks sessions past inactivity threshold as `EXPIRED` (Q4)

---

### 1.5 `schemas.py`

#### [NEW] `src/schemas.py`

Original 5 schemas + 3 new:

| Schema | Status | Notes |
|--------|--------|-------|
| `PrelimsOptionSchema` | Original | No changes |
| `TrapAnalysisSchema` | Original | No changes |
| `ExplanationSchema` | Original | No changes |
| `GeneratedQuestionSchema` | Original | No changes |
| `CriticEvaluationSchema` | Original (from audit) | No changes |
| `SafeModePYQSchema` | **NEW** (Q1) | `question_id`, `question_text`, `options: Dict[str,str]`, `correct_key`, `difficulty_tier`, `subject_id`, `source_year` |
| `TestRequestSchema` | **NEW** (A1+A3) | `subject_code`, `test_type`, `topics: Optional[List[str]]`, `question_count: Optional[int]`, `mode: str`, `study_context: Optional[Dict]` |
| `SubmitAnswerResponseSchema` | **NEW** (Q3) | `score`, `elo_delta`, `psychological_drift_warning: bool`, `warning_reason: Optional[str]` |

> [!IMPORTANT]
> Every `Field()` must include `description=` argument. This is read by the cloud LLM for structured output guidance.

---

### 1.6 `math_utils.py`

#### [NEW] `src/math_utils.py`

All pure functions. No side effects. No DB access. No imports from other project modules except `calibration.py`.

| Function | Formula Source | Key Fix |
|----------|---------------|---------|
| `compute_difficulty_to_elo(difficulty_tier)` | `R_q = tier × 100 + 1000` | Hardcoded mapping |
| `compute_expected_elo(R_old, R_question)` | `E = 1/(1+10^((R_q-R_old)/400))` | Standard Elo |
| `compute_elo_update(R_old, K, P_w, E, floor, ceiling)` | `R_new = R_old + K×(P_w-E)` | Clamp [800, 2000] (C-13) |
| `compute_certainty_weighted_performance(S, confidence, duration, expected, T_max)` | `P_w = S × (C_f × (1-ΔT/T_max))` | Clamp [0.0, 1.0] (C-04) |
| `compute_memory_decay_interval(I_base, alpha, C_f, difficulty_tier, scaler, mistake_count)` | Revised formula (C-03) | `d_t = tier × scaler + mistakes × 0.1`, `exponent = α × C_f × (2.0 − d_t)`, bounds [1.0, 30.0] |
| `update_stability_index(I_base, I_next)` | `0.9×I_base + 0.1×I_next` | C-10 |
| `compute_recovery_velocity(delta_elo, delta_days)` | `V_rec = ΔElo/max(1,Δt)` | C-12 floor |
| `compute_dynamic_time_limit(question_count, question_type)` | **NEW** (A4) | `time = count × expected_seconds` |

---

### 1.7 Unit Tests

#### [NEW] `tests/test_math_utils.py`

Cover all edge cases:
- P_w clamping: negative ΔT, extreme overrun → P_w = 0.0
- Elo floor/ceiling: ratings can't go below 800 or above 2000
- Memory decay bounds: I_next ∈ [1.0, 30.0]
- Recovery velocity: Δt = 0 → floor to 1
- Dynamic time limit: various counts × question types

#### [NEW] `tests/test_calibration.py`

- Config loads successfully
- Live-reload returns updated values
- Missing file → `CalibrationFailure`
- All practice_mode configs accessible

#### [NEW] `tests/test_schemas.py`

- All schemas validate correct payloads
- All schemas reject invalid payloads with clear errors
- `SafeModePYQSchema` validates with/without optional fields
- `TestRequestSchema` validates all 4 modes

#### [NEW] `tests/test_database.py`

- `init_db()` creates all 10 tables
- Session context manager commits/rolls back correctly
- `expire_stale_sessions()` marks old sessions correctly

### Phase 1 Success Criteria

1. `init_db()` runs without error and all 10 tables are present
2. All Pydantic schemas reject invalid payloads with clear errors
3. `math_utils.py` unit tests pass for all edge cases
4. `calibration.py` live-reload works
5. All custom exception classes importable
6. `compute_dynamic_time_limit()` returns correct values for all modes

---

# Phase 2 — Data Ingestion + Onboarding

> [!NOTE]
> Original: `rag_store.py` + `scraper.py`.
> **R5**: `diagnostic.py` moved here from Phase 4 — onboarding happens before the intelligence core is built.
> Add-ons active: **A3** (practice modes data model ready) + **A6** (study context).

## Build Order

```
1. rag_store.py
2. scraper.py
3. diagnostic.py (R5 — moved from Phase 4)
4. Unit tests for Phase 2
```

---

### 2.1 `rag_store.py`

#### [NEW] `src/rag_store.py`

No changes from original spec. Two ChromaDB collections:

| Collection | Content | Consumer |
|------------|---------|----------|
| `syllabus_collection` | UPSC syllabus text chunks | `generator.py` (static RAG) |
| `pyq_collection` | PYQ embeddings 2013–2025 | Critic Agent in `generator.py` |

**Functions:**
- `initialize_collections()` → creates collections silently if absent
- `ingest_syllabus_documents(dir_path)` → one-time
- `ingest_pyq_documents(dir_path)` → one-time
- `retrieve_syllabus_chunks(topic, n_results=5)` → runtime
- `retrieve_similar_pyqs(question_text, n_results=3)` → runtime

**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (local)

**Graceful degradation:** If a collection does not exist or is empty, return an empty list — never hard-fail. The Critic Agent degrades gracefully.

---

### 2.2 `scraper.py`

#### [NEW] `src/scraper.py`

Two-mode architecture as original spec. Two separate functions.

**Mode 1 — `daily_news_scraper()`:**
- Tier 1 (PIB, PRS) + Tier 2 (The Hindu, Indian Express)
- Staging cache → consensus filter → deduplication (cosine ≥ 0.88) → AI synthesis → write to `current_affairs_feed`
- Deduplication uses `sentence-transformers` directly — NOT `rag_store.py` (C-07)
- On Cloud API failure: write with `ai_synthesis=''` rather than discarding

**Mode 2 — `document_ingestor(url, source_type)`:**
- Tier 3 sources, event-triggered via `POST /ingest-document` (Q5)
- Full document → section split → AI synthesis → write to `current_affairs_feed`
- No consensus filter

---

### 2.3 `diagnostic.py` (R5 — moved from Phase 4)

#### [NEW] `src/diagnostic.py`

> [!TIP]
> Moved here so the student has calibrated Elo before Phase 3 builds the adaptive generator. This means Phase 3 testing can exercise real adaptive behavior against calibrated data instead of dummy defaults.

Cold-start only. Does NOT depend on `generator.py` (C-08). Dependencies: `database.py`, `schemas.py`, `calibration.py`, Cloud API.

- 5 subjects × 5 questions = 25 total
- Direct Cloud API calls using `GeneratedQuestionSchema`
- Epoch tracking: record timestamps for pacing baseline
- MCQ accuracy thresholds: >85% → 1450, 50-85% → 1200, <50% → 950
- Sets `baseline_elo_rating` (only unconditional write)
- Writes `weakness_tags` as JSON array
- Initializes `topic_progress` records for detected weak topics
- Terminal output: per-subject Elo + weakness tags printed as they're written

**Partial failure handling:** If Cloud API fails mid-diagnostic, write whatever was computed before failure. A partial calibration is better than no calibration.

---

### Phase 2 Success Criteria

1. `initialize_collections()` creates both ChromaDB collections
2. After ingestion: `retrieve_syllabus_chunks("Fundamental Rights", 5)` → 5 results
3. After ingestion: `retrieve_similar_pyqs("Which of the following...", 3)` → 3 results
4. `daily_news_scraper()` writes at least one record
5. Deduplication merges articles above 0.88 similarity
6. Tier 2 without consensus is NOT written
7. `run_diagnostic()` writes 5 `student_profile` records with non-default Elo (R5)
8. Diagnostic partial failure writes whatever was computed before error (R5)

---

# Phase 3 — Intelligence Core

> [!IMPORTANT]
> This is the **highest-complexity phase**. Original: `generator.py` + `evaluator.py`.
> **R1**: `composition_engine.py` built here from the start — no temporary code in generator.py.
> Add-ons active: **A1** (dynamic topics), **A2** (dynamic counts), **A4** (dynamic timing), **A7** (constraint solver).

## Build Order

```
1. composition_engine.py (R1 — built here, not Phase 5)
2. generator.py (imports composition_engine.py from day one)
3. evaluator.py
4. Integration tests for Phase 3
```

---

### 3.1 `composition_engine.py` (R1 — moved from Phase 5)

#### [NEW] `src/composition_engine.py`

Pure logic module. No Cloud API calls. No DB access. No side effects. Fully unit-testable in isolation.

**Purpose:** Given a set of constraints, produce a question allocation blueprint.

```python
@dataclass
class CompositionConstraints:
    question_count: int
    mode: str                              # DAILY_SPRINT, TOPIC_PRACTICE, etc.
    subject_code: str                      # R3: renamed
    topics: Optional[List[str]]
    study_context: Optional[Dict]
    backlog_items: List[BacklogItem]
    weak_areas: List[str]                  # from student_profile.weakness_tags
    enforce_floor: bool                    # from mode config
    enforce_backlog: bool                  # from mode config
    floor_ratio: float                     # from config
    static_ratio: float                    # from config
    backlog_ratio: float                   # from config

@dataclass
class CompositionPlan:
    floor_count: int
    static_today: int
    static_backlog: int
    ca_today: int
    ca_backlog: int
    total: int                             # Must equal question_count
    floor_topics: List[str]
    backlog_topics: List[str]
    mode: str
    system_intent_header: str

def solve_composition(constraints: CompositionConstraints) → CompositionPlan:
    """
    Constraint solver. Produces a CompositionPlan that satisfies all constraints.
    
    Resolution order:
    1. Floor guarantee (if enforced)
    2. Content type split (static vs CA)
    3. Backlog allocation within each category (if enforced)
    4. Topic filtering (if topics specified)
    5. Study context boost (soft weight, +10-15%)
    6. Weakness area injection into remaining capacity
    
    R4 ROUNDING STRATEGY:
    - All intermediate splits use floor() or round()
    - The FINAL bucket in every split absorbs the remainder:
      ca_count = remaining - static_count  (not round(remaining × ca_ratio))
      ca_today = ca_count - ca_backlog     (not round(ca_count × (1-backlog_ratio)))
    - This guarantees the invariant: all buckets sum to question_count
    - No assertion can fail due to rounding drift
    
    Invariant: plan.total == constraints.question_count
    """
```

**R4 — Remainder-absorb rounding algorithm:**

```
STEP 1: FLOOR
  IF enforce_floor:
    floor_count = round(total × floor_ratio)
  ELSE:
    floor_count = 0

STEP 2: REMAINING
  remaining = total - floor_count

STEP 3: CONTENT SPLIT (last bucket absorbs)
  static_count = round(remaining × static_ratio)
  ca_count = remaining - static_count              ← absorbs remainder

STEP 4: BACKLOG SPLIT (last bucket absorbs, per category)
  IF enforce_backlog AND has_backlog:
    static_backlog = round(static_count × backlog_ratio)
    static_today = static_count - static_backlog   ← absorbs remainder
    ca_backlog = round(ca_count × backlog_ratio)
    ca_today = ca_count - ca_backlog               ← absorbs remainder
  ELSE:
    static_today = static_count
    ca_today = ca_count
    static_backlog = 0
    ca_backlog = 0

STEP 5: TOPIC FILTERING (A1)
  IF topics specified:
    constrain static_today and ca_today to requested topics
    excess redistributed to matching categories

STEP 6: STUDY CONTEXT BOOST (A6)
  IF study_context.today_focus exists:
    apply +10-15% weight toward focus subject within existing allocation
    NOT a hard constraint — redistributes, does not add

# INVARIANT (always true by construction — no assertion needed):
floor_count + static_today + static_backlog + ca_today + ca_backlog == total
```

**Example calculations with R4:**

```
total=15, floor_ratio=0.20, static_ratio=0.60, backlog_ratio=0.35

floor_count = round(15 × 0.20) = round(3.0) = 3
remaining = 15 - 3 = 12
static_count = round(12 × 0.60) = round(7.2) = 7
ca_count = 12 - 7 = 5                    ← absorbs remainder (not round(12×0.40)=5, same here)
static_backlog = round(7 × 0.35) = round(2.45) = 2
static_today = 7 - 2 = 5                 ← absorbs
ca_backlog = round(5 × 0.35) = round(1.75) = 2
ca_today = 5 - 2 = 3                     ← absorbs

Total: 3 + 5 + 2 + 3 + 2 = 15 ✓

total=17, same ratios:
floor_count = round(17 × 0.20) = round(3.4) = 3
remaining = 14
static_count = round(14 × 0.60) = round(8.4) = 8
ca_count = 14 - 8 = 6                    ← absorbs (round(14×0.40)=6, same here)
static_backlog = round(8 × 0.35) = round(2.8) = 3
static_today = 8 - 3 = 5
ca_backlog = round(6 × 0.35) = round(2.1) = 2
ca_today = 6 - 2 = 4

Total: 3 + 5 + 3 + 4 + 2 = 17 ✓
```

---

### 3.2 `generator.py`

#### [NEW] `src/generator.py`

**Key change from original:** Generator does NOT contain composition logic. It imports `composition_engine.solve_composition()` from day one (R1).

**Function signatures:**

```python
def build_constraints_from_context(
    subject_code: str,                      # R3: renamed
    test_type: str,
    total_questions: int = 30,
    mode: str = "DAILY_SPRINT",
    topics: Optional[List[str]] = None,
    study_context: Optional[Dict] = None,
    db_session: Session = None
) → CompositionConstraints:
    """
    Reads DB state (backlog_queue, student_profile.weakness_tags, daily_study_log)
    and config (practice_modes, ratios) to build CompositionConstraints.
    This is the ONLY function in generator.py that touches the DB for composition.
    """

def generate_full_adaptive_exam(
    plan: CompositionPlan,
    session_id: str
) → List[str]:
    """
    Takes a solved CompositionPlan and generates questions.
    Calls Cloud API via asyncio.gather (3 parallel workers × ceil(N/3) questions).
    Runs Critic Agent on each. Writes to question_bank. Returns question_ids.
    """

def run_critic_agent(
    draft_question: GeneratedQuestionSchema,
    similar_pyqs: List[Dict]
) → CriticEvaluationSchema:
    """Unchanged from original spec."""
```

**Flow:**
```python
# In main.py or caller:
constraints = generator.build_constraints_from_context(subject_code, test_type, ...)
plan = composition_engine.solve_composition(constraints)
question_ids = generator.generate_full_adaptive_exam(plan, session_id)
```

**Critic Agent pipeline:** Unchanged from original spec.
- Generate draft → retrieve 3 similar PYQs → Cloud API critic → dual-gate check → max 3 retries → fallback to static pool

**System Intent Header:** Built by `composition_engine.py` as part of `CompositionPlan`. Includes mode and dynamic count:
```
"Today's Test Architecture [TOPIC_PRACTICE | 20 questions]:
 0 Floor, 12 Static Core [Polity: Parliament], 8 CA Today [Polity: Current]"
```

**Dynamic timing (A4):**
```python
time_limit_seconds = math_utils.compute_dynamic_time_limit(
    question_count=plan.total,
    question_type=test_type
)
```
Returned alongside question list in API response.

---

### 3.3 `evaluator.py`

#### [NEW] `src/evaluator.py`

No changes from original spec + audit resolutions.

**Dual-pass adversarial pipeline:**
- Pass 1 — Anchor Validation (blueprint completeness)
- Pass 2 — Adversarial Cross-Examination (sequential, not parallel)

**Interface (C-06 compatible):**
```python
evaluate_mains_response(
    student_response: str,
    confidence_level: str,
    response_duration_seconds: float,
    question_id: Optional[str] = None,
    blueprint: Optional[Dict] = None      # For benchmark_runner compatibility
) → EvaluationResult
```

**Score normalization (C-01):** Raw score ÷ 10.0 before writing to `attempt_history.score_percentage`.

---

### Phase 3 Success Criteria

1. `composition_engine.solve_composition()` returns correct allocation for **all 4 modes** and **variable question counts** (15, 17, 20, 30, 100)
2. **R4**: Remainder-absorb guarantees exact sum for all inputs — no rounding drift
3. `TOPIC_PRACTICE` mode with specific topics only generates questions for those topics
4. `DAILY_SPRINT` mode enforces floor + backlog; `TOPIC_PRACTICE` does not
5. `generate_full_adaptive_exam()` produces N questions (matching plan), all passing schema validation
6. Study context boost is soft (10-15%), not dominant
7. Dynamic time limit calculated correctly for all modes
8. Critic Agent retry → fallback works
9. `evaluate_mains_response()` with direct `blueprint` dict works (benchmark compat)
10. All questions written to `question_bank` with provenance_tags
11. Generator has ZERO composition logic — all delegated to `composition_engine.py` (R1)

---

# Phase 4 — Delivery Layer

> [!NOTE]
> Original: `diagnostic.py` + `pdf_exporter.py` + `safe_mode.py`.
> **R5**: `diagnostic.py` already built in Phase 2.
> Add-on active: **A5** (frontend-controlled inputs — API contract design).
> **R2**: Safe mode freshness aligned to 48h.

## Build Order

```
1. safe_mode.py
2. pdf_exporter.py
3. Tests for Phase 4
```

---

### 4.1 `safe_mode.py`

#### [NEW] `src/safe_mode.py`

Updated for Q1 (SafeModePYQSchema) + R2 (48h freshness):

**`get_fallback_questions(subject_code, count)`:**
- Reads from `static_assets/pyq/prelims/` flat JSON files
- Parses using `SafeModePYQSchema` (not `GeneratedQuestionSchema`)
- Filters by `subject_id` field in schema for adaptive selection even in fallback
- No ChromaDB, no Cloud API
- Returns `List[SafeModePYQSchema]`

**`health_check()`:**
- Ping Cloud API with minimal test call
- Check `current_affairs_feed` freshness using **`config.current_affairs_filters.rolling_window_hours` (48h)** — R2: aligned with scraper's rolling window, not hardcoded 24h
- Returns `HealthStatus` enum: `HEALTHY | DEGRADED_API | DEGRADED_FEED | DEGRADED_BOTH`
- Logs degraded status to `experiment_runs`
- Never raises — returns `DEGRADED_BOTH` on internal error

> [!TIP]
> **R2 rationale:** The scraper uses a 48h consensus window. If health_check() used 24h, a single missed scraper run would trigger safe mode even though the system has valid data from yesterday that the scraper would still consider current. Aligning both to 48h prevents false degradation triggers.

**`is_safe_mode_active()` → `bool`:**
- Calls `health_check()` on each invocation (stateless)
- Returns `True` if any DEGRADED state

---

### 4.2 `pdf_exporter.py`

#### [NEW] `src/pdf_exporter.py`

Unchanged from original spec. Three watermarked A4 PDF documents via ReportLab.

- **Watermark:** "THE FELLOW ASPIRANT", font 52, opacity 0.15, rotation 45°, re-applied after every `showPage()`
- **Cursor management:** `cursor_y < 120` → new page
- Doc 1: `Question_Paper.pdf` — stems + options only, Mains gets 90pt blank space
- Doc 2: `Answer_Key_and_Analysis.pdf` — answer + Core Concept + Trap Analysis
- Doc 3: `Daily_Current_Affairs_Briefing.pdf` — title + syllabus mapping + synthesis

---

### Phase 4 Success Criteria

1. `health_check()` uses 48h window from config (R2 — not hardcoded 24h)
2. `health_check()` returns DEGRADED within 5s of API being unreachable
3. Fallback questions parsed via `SafeModePYQSchema` with `subject_id` filtering
4. All 3 PDFs generated correctly with watermarks on every page
5. Page breaks re-apply watermark
6. Safe mode activation logged to `experiment_runs`

---

# Phase 5 — Orchestration & Observability

> [!NOTE]
> Original: `main.py` + `benchmark_runner.py`.
> A5 frontend contracts realized in API routes.
> A7 composition engine already built in Phase 3 (R1) — Phase 5 just wires it into the API.

## Build Order

```
1. main.py
2. benchmark_runner.py
3. End-to-end tests
```

---

### 5.1 `main.py`

#### [NEW] `src/main.py`

FastAPI application. All business logic delegated to spokes.

**Startup:**
```python
@app.on_event("startup")
→ init_db()
→ load_config()
→ scheduler.add_job(daily_news_scraper, 'cron', hour=6, max_instances=1)
→ scheduler.add_job(archival_hot_to_warm, 'cron', hour=2)
→ scheduler.add_job(archival_warm_to_cold, 'cron', day_of_week='sun', hour=3)
→ scheduler.add_job(expire_stale_sessions, 'cron', minute='*/30')  # Q4
→ scheduler.start()
```

**Routes:**

| Route | Method | Changes |
|-------|--------|---------|
| `/generate-test` | POST | Accepts `TestRequestSchema` (A1-A6). Creates `test_sessions` record. Returns questions + session_id + time_limit + System Intent Header |
| `/submit-answer` | POST | Checks session timeout (Q4). Returns `SubmitAnswerResponseSchema` with `psychological_drift_warning` + `warning_reason` (Q3) |
| `/evaluate/mains` | POST | No changes |
| `/generate-test/export` | POST | No changes |
| `/generate-briefing/export` | POST | No changes |
| `/ingest-document` | POST | **NEW** (Q5): accepts `{source_type, input_mode, resource, subject_code}` |

**`POST /generate-test` — Request (A1+A2+A3+A5+A6):**

```json
{
  "subject_code": "POLITY",
  "test_type": "PRELIMS_GS",
  "mode": "TOPIC_PRACTICE",
  "topics": ["Parliament", "Fundamental Rights"],
  "question_count": 20,
  "study_context": { "today_focus": "POLITY" }
}
```

**Orchestration flow:**
1. Validate via `TestRequestSchema`
2. Run `safe_mode.health_check()` → route to safe mode if degraded
3. Create `test_sessions` record with `student_id='default'` (R3), `subject_code`, metadata
4. `generator.build_constraints_from_context(...)` → constraints
5. `composition_engine.solve_composition(constraints)` → plan
6. `generator.generate_full_adaptive_exam(plan, session_id)` → questions
7. `time_limit = math_utils.compute_dynamic_time_limit(count, type)` (A4)
8. Return questions + session_id + time_limit + System Intent Header

**`POST /submit-answer` — Response (Q3):**

```json
{
  "score": 0.74,
  "elo_delta": 18,
  "psychological_drift_warning": true,
  "warning_reason": "High pacing variance detected (σ = 0.52)"
}
```

**Session timeout handling (Q4):**
- On `/submit-answer`: check `test_sessions.last_activity_at`
- If `now - last_activity_at > config.session.inactivity_timeout_minutes` → mark session `EXPIRED`, return error
- Update `last_activity_at` on each valid submission
- Session ends when all questions submitted OR timeout
- `expire_stale_sessions()` runs every 30 min via APScheduler as background cleanup

**`POST /ingest-document` — Request (Q5):**

```json
{
  "source_type": "STATIC_SOURCE",
  "input_mode": "URL",
  "resource": "https://...",
  "subject_code": "POLITY"
}
```

**Error handling:**
All custom exceptions → structured JSON payloads:
```json
{
  "error_code": "GenerationFailure",
  "message": "...",
  "safe_mode_available": true
}
```

---

### 5.2 `benchmark_runner.py`

#### [NEW] `src/benchmark_runner.py`

Updated for Q2 (blueprint caching):

**Part 1 — Generation Validation:** Unchanged.

**Part 2 — Evaluation Validation (Q2 updated):**

```python
def run_evaluation_benchmark():
    for topper_file in static_assets/topper_copies/*.txt:
        blueprint_cache = topper_file.replace('.txt', '.blueprint.json')
        
        if blueprint_cache exists:
            blueprint = load(blueprint_cache)       # Reuse cached
        else:
            blueprint = cloud_api.generate_blueprint(topper_file)
            save(blueprint, blueprint_cache)         # Cache for next run
        
        result = evaluator.evaluate_mains_response(
            student_response=topper_text,
            blueprint=blueprint,                     # C-06 compatible
            confidence_level="HIGH",
            response_duration_seconds=450
        )
        
        if result.score_normalized < 0.85:
            print("System Drift Warning: Evaluation calibration degraded")
        
        write_to_experiment_runs(result)
```

**Drift thresholds:**
- Generation quality below PYQ semantic density → warning
- Topper copies below 8.5/10 (0.85 normalized) → warning

---

### Phase 5 Success Criteria

1. Server starts without error, all routes respond
2. `/generate-test` accepts all 4 practice modes with variable question counts
3. `TOPIC_PRACTICE` with `topics=["Parliament"]` generates only Parliament questions
4. `study_context` applies soft boost without dominating allocation
5. Session timeout correctly expires sessions after 2h inactivity
6. `/submit-answer` returns `psychological_drift_warning` when σ > 0.40
7. `/ingest-document` triggers `document_ingestor()` correctly
8. Blueprint caching works — second benchmark run reuses cached `.blueprint.json`
9. APScheduler fires all jobs on schedule including `expire_stale_sessions`
10. `subject_code` used consistently across API payloads and `test_sessions` (R3)

---

# Verification Plan

### Automated Tests

```bash
# Phase 1
pytest tests/test_math_utils.py -v
pytest tests/test_calibration.py -v
pytest tests/test_schemas.py -v
pytest tests/test_database.py -v

# Phase 2
pytest tests/test_rag_store.py -v
pytest tests/test_scraper.py -v
pytest tests/test_diagnostic.py -v

# Phase 3
pytest tests/test_composition_engine.py -v   # All 4 modes × variable counts × R4 rounding
pytest tests/test_generator.py -v
pytest tests/test_evaluator.py -v

# Phase 4
pytest tests/test_safe_mode.py -v
pytest tests/test_pdf_exporter.py -v

# Phase 5
pytest tests/test_main.py -v                 # API route integration tests
pytest tests/test_benchmark_runner.py -v

# Full suite
pytest tests/ -v --tb=short
```

### Manual Verification

- Run `diagnostic.py` (Phase 2) → confirm 5 subject Elo values printed to terminal
- Generate a test via API → confirm N-question PDF with watermarks
- Simulate Cloud API failure → confirm safe mode activates and serves PYQs via SafeModePYQSchema
- Run `benchmark_runner.py` → confirm blueprint caching creates `.blueprint.json` files
- Test all 4 practice modes via API → confirm different composition behaviors
- Verify session timeout → submit after 2h+ gap → confirm `EXPIRED` response
- Verify safe mode uses 48h window (R2) — scraper down for 30h should NOT trigger degradation

---

# Refinement Traceability

| Refinement | Where Applied | Verification |
|-----------|---------------|-------------|
| R1 — composition_engine.py in Phase 3 | Phase 3 build order, generator.py has zero composition logic | Phase 3 success criterion #11 |
| R2 — Safe mode 48h alignment | `safe_mode.health_check()` reads from config, not hardcoded | Phase 4 success criterion #1, manual verification |
| R3 — test_sessions field rename | `student_id` + `subject_code` in models.py, schemas, API payloads | Phase 5 success criterion #10 |
| R4 — Remainder-absorb rounding | `composition_engine.solve_composition()` algorithm | Phase 3 success criterion #2, test_composition_engine.py |
| R5 — diagnostic.py in Phase 2 | Phase 2 build order step 3 | Phase 2 success criteria #7, #8 |

---

## Open Items — None

All architectural decisions frozen. All contradictions resolved. All add-ons placed. All refinements applied.

**Ready for Phase 1 implementation on your approval.**
