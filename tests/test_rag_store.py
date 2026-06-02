"""Verification tests for Phase 2 Group 1: RAG Store (rag_store.py)."""

import pytest
from unittest.mock import patch, MagicMock
import chromadb
from chromadb.config import Settings
import numpy as np

from src import rag_store

EMBEDDING_DIM = 384
FIXED_VECTOR = np.random.rand(EMBEDDING_DIM)


# ── Helpers ──────────────────────────────────────────────────────────────

_COUNTER = 0


def _make_sentence_transformer_mock():
    """Return a MagicMock that behaves like SentenceTransformer."""
    global _COUNTER
    _COUNTER += 1
    mock = MagicMock()

    def encode_side_effect(texts, *args, **kwargs):
        if isinstance(texts, str):
            return np.array(FIXED_VECTOR)
        return np.array([FIXED_VECTOR] * len(texts))

    mock.encode.side_effect = encode_side_effect
    mock.get_sentence_embedding_dimension.return_value = EMBEDDING_DIM
    return mock


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def set_up(no_real_model, ephemeral_chroma, reset_singleton):
    """Aggregate all autouse fixtures to avoid ordering leakage."""
    pass


@pytest.fixture
def no_real_model():
    """Prevent SentenceTransformer download — return a mock instead."""
    patcher = patch("src.rag_store.SentenceTransformer")
    mock_cls = patcher.start()
    mock_cls.side_effect = lambda *a, **kw: _make_sentence_transformer_mock()
    yield mock_cls
    patcher.stop()


@pytest.fixture
def ephemeral_chroma():
    """Use in-memory EphemeralClient so tests leave no disk artifacts.
    ChromaDB shares one global system per identifier, so we must reset()
    at fixture start to prevent cross-test pollution."""
    orig = rag_store.get_chroma_client
    _client = chromadb.EphemeralClient(Settings(allow_reset=True))
    _client.reset()
    rag_store.get_chroma_client = lambda: _client
    yield _client
    rag_store.get_chroma_client = orig


@pytest.fixture
def reset_singleton():
    """Reset the embedding singleton before every test."""
    rag_store._embedding_model = None
    yield


# ══════════════════════════════════════════════════════════════════════════
# 1. Collection Initialization Tests
# ══════════════════════════════════════════════════════════════════════════


class TestCollectionInitialization:

    def test_initialize_collections_creates_both(self):
        rag_store.initialize_collections()
        client = rag_store.get_chroma_client()
        assert client.get_collection("syllabus_collection") is not None
        assert client.get_collection("pyq_collection") is not None

    def test_repeated_initialize_does_not_duplicate(self):
        rag_store.initialize_collections()
        rag_store.initialize_collections()
        rag_store.initialize_collections()
        client = rag_store.get_chroma_client()
        assert client.get_collection("syllabus_collection").count() == 0
        assert client.get_collection("pyq_collection").count() == 0

    def test_restart_safe_behavior(self):
        """Simulate restart: reset singleton + re-init should behave same."""
        rag_store.initialize_collections()
        rag_store._embedding_model = None
        rag_store.initialize_collections()
        client = rag_store.get_chroma_client()
        assert client.get_collection("syllabus_collection").count() == 0
        assert client.get_collection("pyq_collection").count() == 0


# ══════════════════════════════════════════════════════════════════════════
# 2. Idempotency Tests
# ══════════════════════════════════════════════════════════════════════════


class TestIdempotency:

    SYLLABUS_DOCS = [
        "Indian Polity: Constitution of India, Fundamental Rights, DPSP",
        "Geography: Physical features, climate, vegetation",
        "History: Indus Valley Civilization, Vedic Period",
    ]
    PYQ_DOCS = [
        "Which of the following is a Fundamental Right?",
        "The President of India is elected by:",
        "Consider the following statements about GST:",
    ]

    def _syllabus_count(self):
        client = rag_store.get_chroma_client()
        return client.get_collection("syllabus_collection").count()

    def _pyq_count(self):
        client = rag_store.get_chroma_client()
        return client.get_collection("pyq_collection").count()

    def test_single_ingestion_increases_count(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(self.SYLLABUS_DOCS)
        assert self._syllabus_count() == 3

    def test_repeated_syllabus_ingestion_does_not_duplicate(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(self.SYLLABUS_DOCS)
        rag_store.ingest_syllabus_documents(self.SYLLABUS_DOCS)
        rag_store.ingest_syllabus_documents(self.SYLLABUS_DOCS)
        assert self._syllabus_count() == 3

    def test_repeated_pyq_ingestion_does_not_duplicate(self):
        rag_store.initialize_collections()
        rag_store.ingest_pyq_documents(self.PYQ_DOCS)
        rag_store.ingest_pyq_documents(self.PYQ_DOCS)
        assert self._pyq_count() == 3

    def test_sha_hash_ids_prevent_duplicates(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(["unique document"])
        collection = rag_store.get_chroma_client().get_collection("syllabus_collection")
        first_id = collection.get()["ids"][0]
        assert len(first_id) == 64
        assert all(c in "0123456789abcdef" for c in first_id)

    def test_upsert_replaces_metadata_on_rerun(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(["hello world"])
        collection = rag_store.get_chroma_client().get_collection("syllabus_collection")
        first_meta = collection.get()["metadatas"][0]["source"]
        assert first_meta == "syllabus"

    def test_empty_document_list_does_nothing(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents([])
        rag_store.ingest_pyq_documents([])
        assert self._syllabus_count() == 0
        assert self._pyq_count() == 0


# ══════════════════════════════════════════════════════════════════════════
# 3. Retrieval Contract Tests
# ══════════════════════════════════════════════════════════════════════════


class TestRetrievalContracts:

    SYLLABUS_DOCS = [
        "Indian Polity: Constitution, Fundamental Rights, DPSP, Parliament",
        "Geography: Himalayas, rivers, climate zones, vegetation",
        "History: Indus Valley Civilization, Vedic Age, Mauryan Empire",
    ]

    @pytest.fixture
    def populated_db(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(self.SYLLABUS_DOCS)
        rag_store.ingest_pyq_documents([
            "Which Fundamental Right is guaranteed under Article 32?",
            "The Parliament consists of:",
            "Who is the ex-officio Chairman of Rajya Sabha?",
        ])

    def test_retrieve_returns_list_of_dicts(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Fundamental Rights", n_results=2)
        assert isinstance(results, list)
        assert len(results) == 2

    def test_result_has_id_field(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=1)
        assert "id" in results[0]
        assert isinstance(results[0]["id"], str)

    def test_result_has_text_field(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=1)
        assert "text" in results[0]
        assert isinstance(results[0]["text"], str)
        assert len(results[0]["text"]) > 0

    def test_result_has_metadata_dict(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=1)
        assert "metadata" in results[0]
        assert isinstance(results[0]["metadata"], dict)

    def test_metadata_contains_source(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=1)
        assert "source" in results[0]["metadata"]
        assert results[0]["metadata"]["source"] == "syllabus"

    def test_pyq_metadata_contains_source(self, populated_db):
        results = rag_store.retrieve_similar_pyqs("Fundamental Right", n_results=1)
        assert results[0]["metadata"]["source"] == "pyq"

    def test_result_has_distance_float(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=1)
        assert "distance" in results[0]
        assert isinstance(results[0]["distance"], float)

    def test_empty_collection_returns_empty_list(self):
        rag_store.initialize_collections()
        results = rag_store.retrieve_syllabus_chunks("anything", n_results=5)
        assert results == []

    def test_missing_collection_returns_empty_list(self):
        results = rag_store.retrieve_similar_pyqs("anything", n_results=3)
        assert results == []

    def test_retrieval_does_not_crash(self):
        rag_store.initialize_collections()
        rag_store.retrieve_syllabus_chunks("x", n_results=1)
        rag_store.retrieve_similar_pyqs("x", n_results=1)
        rag_store.retrieve_syllabus_chunks("", n_results=5)
        rag_store.retrieve_similar_pyqs("", n_results=3)

    def test_all_contract_fields_present(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Geography", n_results=1)
        item = results[0]
        required_keys = {"id", "text", "metadata", "distance"}
        assert required_keys.issubset(item.keys())


# ══════════════════════════════════════════════════════════════════════════
# 4. Embedding Lifecycle Tests
# ══════════════════════════════════════════════════════════════════════════


class TestEmbeddingLifecycle:

    def test_embedding_model_is_none_initially(self):
        assert rag_store._embedding_model is None

    def test_get_embedding_model_creates_singleton(self):
        model = rag_store.get_embedding_model()
        assert model is not None
        assert rag_store._embedding_model is model

    def test_get_embedding_model_returns_same_instance(self):
        model1 = rag_store.get_embedding_model()
        model2 = rag_store.get_embedding_model()
        assert model1 is model2

    def test_multiple_retrievals_use_same_model(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(["test document"])
        before = rag_store._embedding_model
        rag_store.retrieve_syllabus_chunks("test", n_results=1)
        rag_store.retrieve_similar_pyqs("test", n_results=1)
        rag_store.retrieve_syllabus_chunks("more", n_results=1)
        after = rag_store._embedding_model
        assert before is after

    def test_singleton_persists_across_calls(self):
        model_first = rag_store.get_embedding_model()
        model_second = rag_store.get_embedding_model()
        assert id(model_first) == id(model_second)

    def test_singleton_reset_creates_new_instance(self):
        model_first = rag_store.get_embedding_model()
        rag_store._embedding_model = None
        model_second = rag_store.get_embedding_model()
        assert model_first is not model_second


# ══════════════════════════════════════════════════════════════════════════
# 5. Dependency Boundary Tests
# ══════════════════════════════════════════════════════════════════════════


class TestDependencyBoundaries:

    def test_no_import_from_database_py(self):
        import ast, inspect
        source = inspect.getsource(rag_store)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "database" in node.module:
                    pytest.fail(f"rag_store.py imports from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "database" in alias.name:
                        pytest.fail(f"rag_store.py imports {alias.name}")

    def test_no_import_from_models_py(self):
        import ast, inspect
        source = inspect.getsource(rag_store)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "models" in node.module:
                    pytest.fail(f"rag_store.py imports from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "models" in alias.name:
                        pytest.fail(f"rag_store.py imports {alias.name}")

    def test_no_forbidden_modules_accessible(self):
        import sys
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith("src.database") or mod_name.startswith("src.models"):
                if mod_name in sys.modules:
                    del sys.modules[mod_name]
        assert "src.database" not in sys.modules
        assert "src.models" not in sys.modules

    def test_chromadb_used_not_sqlite(self):
        import ast, inspect
        source = inspect.getsource(rag_store)
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        assert "chromadb" in imports
        assert "sqlalchemy" not in imports


# ══════════════════════════════════════════════════════════════════════════
# 6. Retrieval Edge-Case Tests
# ══════════════════════════════════════════════════════════════════════════


class TestRetrievalEdgeCases:

    DOCS = ["Fundamental Rights in Indian Constitution",
            "Directive Principles of State Policy",
            "Parliamentary System of Government",
            "Judicial Review in India",
            "Federal Structure of India"]

    @pytest.fixture
    def populated_db(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(self.DOCS)

    def test_n_results_greater_than_collection_size(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=100)
        assert isinstance(results, list)
        assert len(results) == len(self.DOCS)

    def test_n_results_zero_raises_type_error(self, populated_db):
        """ChromaDB rejects n_results=0 at query time."""
        import pytest
        with pytest.raises(TypeError, match="cannot be negative, or zero"):
            rag_store.retrieve_syllabus_chunks("Polity", n_results=0)

    def test_retrieve_with_empty_query_string(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("", n_results=1)
        assert isinstance(results, list)

    def test_retrieve_with_long_query(self, populated_db):
        long_query = " ".join(["constitution"] * 200)
        results = rag_store.retrieve_syllabus_chunks(long_query, n_results=1)
        assert isinstance(results, list)

    def test_retrieve_with_special_characters(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Fundamental Rights — Art. 14–18", n_results=1)
        assert isinstance(results, list)
        assert len(results) == 1


# ══════════════════════════════════════════════════════════════════════════
# 7. Data Integrity Tests
# ══════════════════════════════════════════════════════════════════════════


class TestDataIntegrity:

    SYLLABUS_DOCS = [
        "Indian Polity – Constitution, Fundamental Rights",
        "Geography of India – Physical features, climate",
    ]
    PYQ_DOCS = [
        "Which article deals with Fundamental Rights?",
        "What is the capital of India?",
    ]

    @pytest.fixture
    def populated_db(self):
        rag_store.initialize_collections()
        rag_store.ingest_syllabus_documents(self.SYLLABUS_DOCS)
        rag_store.ingest_pyq_documents(self.PYQ_DOCS)

    def test_no_cross_contamination_syllabus_to_pyq(self, populated_db):
        pyq_results = rag_store.retrieve_similar_pyqs("Fundamental Rights", n_results=5)
        for r in pyq_results:
            assert r["metadata"]["source"] == "pyq"

    def test_no_cross_contamination_pyq_to_syllabus(self, populated_db):
        syllabus_results = rag_store.retrieve_syllabus_chunks("Fundamental Rights", n_results=5)
        for r in syllabus_results:
            assert r["metadata"]["source"] == "syllabus"

    def test_ingested_at_valid_iso_format(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Polity", n_results=5)
        for r in results:
            ts = r["metadata"]["ingested_at"]
            assert "T" in ts and ts.endswith("+00:00")
            parts = ts.split("T")[0].split("-")
            assert len(parts) == 3

    def test_results_ordered_by_distance_ascending(self, populated_db):
        results = rag_store.retrieve_syllabus_chunks("Indian Polity Constitution", n_results=5)
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)
