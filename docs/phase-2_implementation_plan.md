# Phase 2 Implementation Plan: Data Ingestion & Onboarding

## Section 1: Phase 2 Understanding

Phase 2 transitions the system from isolated foundations (Phase 1) into active state generation. It initializes the agent's knowledge stores (RAG), fetches real-world data (Scraper), and onboards the student (Diagnostic). This ensures that Phase 3 adaptive logic can be built on top of live data and real calibrated user baselines.

---

## Section 2: Implementation Groups

### Group 1: The Vector Store

#### Files In Scope
* `src/rag_store.py`

#### Responsibilities
* Initialize ChromaDB collections (`syllabus_collection`, `pyq_collection`).
* Mandate a Singleton embedding loader to manage `sentence-transformers/all-MiniLM-L6-v2` lifecycle centrally, preventing memory exhaustion and repeated initialization latency.
* Ingest syllabus and PYQ documents using document-hash IDs.
* Enforce duplicate prevention strategy using upsert behavior for safe rerun guarantees (Idempotency).
* Retrieve nearest neighbors at runtime.

#### Dependencies Required Before Starting
* Phase 0 Environment setup (ChromaDB, `sentence-transformers/all-MiniLM-L6-v2` downloaded).

#### Constraints
* **Must fail gracefully:** If collections do not exist or are empty, retrieval functions must return `[]` instantly, never throwing exceptions.
* **No Database coupling:** Must NOT interact with SQLite (`models.py` or `database.py`).
* **Do not touch:** Any Phase 1 files.

#### Verification Gate
* **Test File:** `tests/test_rag_store.py`
* **Expected behaviors:** 
  * Ingesting the same document twice (same hash) does not increase collection count. 
  * Querying an empty DB returns `[]` without throwing exceptions.
* **Architecture checks:** Ensure embeddings execute locally, zero network calls.

#### Exit Criteria
* All tests in `test_rag_store.py` pass. Collections instantiate on disk locally without locking errors.

#### Risks
* ChromaDB directory locking in concurrent environments.
* Idempotency failure leading to vector bloat on repeated executions.

---

### Group 2: The Data Scraper

#### Files In Scope
* `src/scraper.py`

#### Responsibilities
* Execute explicit pipeline: Fetch `daily_news_scraper` (Tier 1/2) and `document_ingestor` (Tier 3) → write to staging cache (STRICTLY temporary SQLite table; in-memory lists are banned) → apply consensus filter → perform cosine similarity deduplication (threshold ≥ 0.88) → synthesize articles via Cloud API → write to `current_affairs_feed`.
* Include cleanup behavior to clear staging cache on success/failure and crash recovery to clear stale staging rows on startup.

#### Dependencies Required Before Starting
* Phase 1 `database.py`, `models.py` (`CurrentAffairsFeed`).
* `sentence-transformers` available locally.

#### Constraints
* **Forbidden imports:** Must NOT import `rag_store.py` for deduplication (Constraint C-07).
* **Graceful degradation:** If AI synthesis fails, write the record with `ai_synthesis=''`.
* **Consensus:** Tier 2 requires minimum source consensus; Tier 3 does not.
* **Do not touch:** Any Phase 1 files or `src/rag_store.py`.

#### Verification Gate
* **Test File:** `tests/test_scraper.py`
* **Expected behaviors:** 
  * Deduplication correctly drops simulated articles with cosine similarity >= 0.88. 
  * Exceptions during mocked API calls still save the raw un-synthesized articles to the database. 
  * Staging tables are cleared on both success and mock failure.
* **Architecture checks:** Prove C-07 (no RAG store imports).

#### Exit Criteria
* All tests pass. Scraper pipeline handles failures gracefully without memory leaks or locking tables permanently.

#### Risks
* Cloud API timeouts blocking the daily cron job.
* Out-of-memory errors if the staging cache is bypassed and massive feeds are loaded entirely into memory.

---

### Group 3: The Diagnostic Onboarding

#### Files In Scope
* `src/diagnostic.py`

#### Responsibilities
* Execute the 25-question cold-start diagnostic.
* Record response pacing (epoch timestamps).
* Calculate and set `baseline_elo_rating`.
* Populate `weakness_tags`.
* Initialize `topic_progress` records for ALL required topics using defaults.
* Apply weakness adjustments to the newly initialized topics based on diagnostic results.
* Initialize review metadata for scheduling.
* Preserve diagnostic weakness tagging.

#### Dependencies Required Before Starting
* Phase 1 `database.py`, `models.py`, `schemas.py` (`GeneratedQuestionSchema`), `calibration.py`.

#### Constraints
* **Forbidden imports:** Must NOT depend on `generator.py` (Constraint C-08).
* **Partial failure handling:** Mid-run exceptions or user drop-offs must save the previously computed Elos to `student_profile`.
* **Direct generation:** Must generate questions directly via Cloud API calls.
* **Do not touch:** Any Phase 1 files.

#### Verification Gate
* **Test File:** `tests/test_diagnostic.py`
* **Expected behaviors:** 
  * All defined syllabus topics are initialized in the database even if the student performs well. 
  * Mock Cloud API failure at question 15 still saves Elos for the first 14 questions. 
  * Thresholds correctly assign Elos. Must explicitly reject hardcoded numbers and pull dynamically via `calibration.get_config().diagnostic` to avoid configuration drift.
* **Architecture checks:** Prove C-08 (no generator imports).

#### Exit Criteria
* All tests pass. Database integration tests confirm all `topic_progress` rows exist post-diagnostic and partial saves execute securely.

#### Risks
* Silent failures dropping user calibration data completely.
* Future phase leakage if it accidentally imports or assumes intelligence core components (like the generator) exist.

---

### Group 4: Phase 2 Verification (Integration)

#### Files In Scope
* `tests/test_phase2_integration.py`

#### Responsibilities
* Verify End-to-End ingestion and onboarding without regressions to Phase 1.

#### Dependencies Required Before Starting
* Group 1, Group 2, and Group 3 complete.

#### Constraints
* **Use mocked endpoints:** Must use only mocked Cloud APIs to avoid LLM costs during CI.
* **No DB mutations:** Tests must rollback after execution (preserve testing DB cleanliness).

#### Verification Gate
* Integration suite runs zero regressions against Phase 1 constraints while executing Phase 2 components in sequence.

#### Exit Criteria
* 100% test pass rate relying solely on behavior-driven verification gates (arbitrary >90% coverage targets are removed).

#### Risks
* Hidden coupling between Phase 2 components violating strict boundaries (e.g. Scraper accidentally writing to RAG collections).
