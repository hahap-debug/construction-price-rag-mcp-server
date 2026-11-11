"""Integration tests for Hybrid Retrieval Engine."""

from datetime import date
from app.database.sqlite_db import SQLiteDatabase
from app.database.vector_db import VectorDatabase
from app.retrieval.hybrid_retriever import HybridRetriever


def test_hybrid_retriever_all_seven_core_queries():
    """Verify all 7 requirement queries execute and return high-confidence results."""
    sqlite_db = SQLiteDatabase("data/price.db")
    vector_db = VectorDatabase(persist_directory="data/faiss_index")
    retriever = HybridRetriever(sqlite_db=sqlite_db, vector_db=vector_db)

    # 1. เหล็ก DB12 ราคาเท่าไร
    r1 = retriever.retrieve(query="เหล็ก DB12 ราคาเท่าไร", record_type="material")
    assert r1.status == "success"
    assert r1.results[0].price_id == "MAT-014"
    assert "DB12" in r1.results[0].item_name

    # 2. ราคาเหล็กข้ออ้อย
    r2 = retriever.retrieve(query="ราคาเหล็กข้ออ้อย", record_type="material")
    assert r2.status == "success"
    top_pids = [item.price_id for item in r2.results[:3]]
    assert "MAT-014" in top_pids or "MAT-015" in top_pids

    # 3. ราคาเหล็กทำปลอกเสา
    r3 = retriever.retrieve(query="ราคาเหล็กทำปลอกเสา", record_type="material")
    assert r3.status == "success"
    assert r3.results[0].price_id == "MAT-012"
    assert "RB6" in r3.results[0].item_name

    # 4. ปูนซีเมนต์ 1 ถุงราคาเท่าไร
    r4 = retriever.retrieve(query="ปูนซีเมนต์ 1 ถุงราคาเท่าไร", record_type="material")
    assert r4.status == "success"
    assert "ปูนซีเมนต์" in r4.results[0].item_name

    # 5. ค่าแรงก่ออิฐราคาเท่าไร
    r5 = retriever.retrieve(query="ค่าแรงก่ออิฐราคาเท่าไร", record_type="labor")
    assert r5.status == "success"
    assert r5.results[0].price_id == "LAB-001"
    assert "ก่ออิฐ" in r5.results[0].item_name

    # 6. ขอราคาวัสดุประเภทคอนกรีต
    r6 = retriever.retrieve(query="ขอราคาวัสดุประเภทคอนกรีต", record_type="material")
    assert r6.status == "success"
    assert any("คอนกรีต" in item.item_name for item in r6.results)

    # 7. ค้นหาราคาวัสดุที่มีหน่วยเป็น กก.
    r7 = retriever.retrieve(query="ค้นหาราคาวัสดุที่มีหน่วยเป็น กก.", record_type="material", unit="กก.")
    assert r7.status == "success"
    for item in r7.results:
        assert item.unit == "กก."


def test_hybrid_retriever_date_filtering():
    """Verify effective date filter excludes future prices."""
    sqlite_db = SQLiteDatabase("data/price.db")
    retriever = HybridRetriever(sqlite_db=sqlite_db, vector_db=None)

    # Query with date before July 2026 (e.g. 2025-01-01)
    res = retriever.retrieve(query="เหล็ก DB12", as_of=date(2025, 1, 1))
    # Should not return records dated 2026-07-01
    assert res.total_results == 0


def test_hybrid_retriever_unmatched_unit_returns_no_results():
    """Verify search with incompatible unit does not return wrong unit silently."""
    sqlite_db = SQLiteDatabase("data/price.db")
    retriever = HybridRetriever(sqlite_db=sqlite_db, vector_db=None)

    # Cement bag queried with unit 'ตัน' (ton) - should not match 'ถุง' silently
    res = retriever.retrieve(query="ปูนซีเมนต์ผสม", unit="ตัน")
    assert res.status == "no_results"
    assert res.total_results == 0
