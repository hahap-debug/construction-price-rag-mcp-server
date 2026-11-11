"""Unit tests for Exact Search Retriever."""

from app.database.sqlite_db import SQLiteDatabase
from app.retrieval.exact_retriever import ExactRetriever


def test_exact_search_identical_match():
    """Verify exact match when query is identical to database item name."""
    db = SQLiteDatabase("data/price.db")
    records = db.get_all_prices("material")
    retriever = ExactRetriever()

    query = "เหล็กเส้นข้ออ้อย SD40 ขนาด DB12 มม. (ยาว 10 ม.) / Deformed Bar SD40 DB12mm (10m)"
    results = retriever.search(query=query, records=records)

    assert len(results) >= 1
    assert results[0]["price_id"] == "MAT-014"
    assert results[0]["score"] == 1.0
    assert results[0]["retrieval_method"] == "exact"


def test_exact_search_with_question_words():
    """Verify cleaned exact match when query includes Thai question words."""
    db = SQLiteDatabase("data/price.db")
    records = db.get_all_prices("material")
    retriever = ExactRetriever()

    query = "ราคา เหล็กเส้นข้ออ้อย SD40 ขนาด DB12 มม. (ยาว 10 ม.) / Deformed Bar SD40 DB12mm (10m) เท่าไร"
    results = retriever.search(query=query, records=records)

    assert len(results) >= 1
    assert results[0]["price_id"] == "MAT-014"
    assert results[0]["score"] >= 0.98


def test_exact_search_core_spec():
    """Verify core spec match before parentheses."""
    db = SQLiteDatabase("data/price.db")
    records = db.get_all_prices("material")
    retriever = ExactRetriever()

    query = "เหล็กเส้นข้ออ้อย SD40 ขนาด DB12 มม."
    results = retriever.search(query=query, records=records)

    assert len(results) >= 1
    assert results[0]["price_id"] == "MAT-014"
