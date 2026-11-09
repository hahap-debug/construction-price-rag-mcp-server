"""Unit tests for Semantic Search Retriever with FAISS."""

from app.database.sqlite_db import SQLiteDatabase
from app.database.vector_db import VectorDatabase
from app.retrieval.semantic_retriever import SemanticRetriever


def test_semantic_retrieval_query():
    """Verify semantic retrieval queries FAISS and retrieves SQLite record."""
    sqlite_db = SQLiteDatabase("data/price.db")
    vector_db = VectorDatabase(persist_directory="data/faiss_index")
    retriever = SemanticRetriever(vector_db=vector_db, sqlite_db=sqlite_db, similarity_threshold=0.30)

    results = retriever.search(query="วัสดุก่ออิฐผนัง", record_type="material", max_results=5)
    assert len(results) > 0

    # Ensure all results contain PriceRecord objects hydrated from SQLite
    for r in results:
        assert r["record"].price_id.startswith("MAT-")
        assert r["retrieval_method"] == "semantic"
        assert r["score"] >= 0.30


def test_semantic_retrieval_none_vector_db():
    """Verify semantic retriever handles None vector_db gracefully without error."""
    sqlite_db = SQLiteDatabase("data/price.db")
    retriever = SemanticRetriever(vector_db=None, sqlite_db=sqlite_db)

    results = retriever.search(query="เหล็กเส้น", max_results=5)
    assert results == []
