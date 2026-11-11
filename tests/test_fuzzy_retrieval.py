"""Unit tests for Fuzzy Search Retriever with RapidFuzz and Spec Conflict Guardrails."""

from app.database.sqlite_db import SQLiteDatabase
from app.retrieval.fuzzy_retriever import FuzzyRetriever


def test_fuzzy_search_typo_handling():
    """Verify fuzzy search can find correct rebar despite Thai typo 'ข้ออ่อย'."""
    db = SQLiteDatabase("data/price.db")
    records = db.get_all_prices("material")
    retriever = FuzzyRetriever(similarity_threshold=0.35)

    query = "เหล็กข้ออ่อย DB12"
    results = retriever.search(query=query, records=records)

    assert len(results) > 0
    top = results[0]
    assert top["price_id"] == "MAT-014"
    assert "DB12" in top["record"].item_name
    assert top["score"] >= 0.70


def test_fuzzy_spec_conflict_guard():
    """Verify query for DB12 severely penalizes DB16 and DB20."""
    db = SQLiteDatabase("data/price.db")
    records = db.get_all_prices("material")
    retriever = FuzzyRetriever(similarity_threshold=0.20)

    query = "เหล็กเส้นข้ออ้อย SD40 DB12"
    results = retriever.search(query=query, records=records)

    db12_results = [r for r in results if r["price_id"] == "MAT-014"]
    db16_results = [r for r in results if r["price_id"] == "MAT-015"]

    assert len(db12_results) == 1
    # DB12 score should be significantly higher than conflicting DB16
    assert db12_results[0]["score"] > 0.85
    if db16_results:
        assert db12_results[0]["score"] > db16_results[0]["score"] * 1.5


def test_fuzzy_usage_keyword_boost():
    """Verify 'ปลอกเสา' boosts round rebar RB6 over main bar."""
    db = SQLiteDatabase("data/price.db")
    records = db.get_all_prices("material")
    retriever = FuzzyRetriever(similarity_threshold=0.35)

    query = "ราคาเหล็กทำปลอกเสา"
    results = retriever.search(query=query, records=records)

    assert len(results) > 0
    assert results[0]["price_id"] == "MAT-012"
    assert "RB6" in results[0]["record"].item_name
