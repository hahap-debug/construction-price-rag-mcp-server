"""Unit and Integration tests for FastMCP Tools and Service Layer."""

from server import mcp
from app.services.price_service import PriceService


def test_mcp_server_tool_registration():
    """Verify match_material and rebuild_price_database are registered on the FastMCP server."""
    provider = mcp._local_provider
    registered_keys = list(provider._components.keys())

    assert "tool:match_material@" in registered_keys
    assert "tool:rebuild_price_database@" in registered_keys
    assert len(registered_keys) == 2


def test_mcp_rebuild_price_database_tool():
    """Verify rebuild_price_database cleans and rebuilds database correctly."""
    tool = mcp._local_provider._components["tool:rebuild_price_database@"]
    res = tool.fn()
    assert res["status"] == "success"
    assert res["total_records"] > 0
    assert res["materials_imported"] > 0
    assert res["labor_imported"] > 0
    assert "vector_index_size" in res


def test_rebuild_price_database_validations(tmp_path):
    """Verify validations: non-excel rejection, missing file, and missing 'วัสดุพื้นฐาน' sheet."""
    import openpyxl
    svc = PriceService()

    # 1. Non-excel file
    dummy_txt = tmp_path / "notes.txt"
    dummy_txt.write_text("hello", encoding="utf-8")
    res1 = svc.rebuild_database(str(dummy_txt))
    assert res1["status"] == "error"
    assert "ไม่ใช่ไฟล์ Excel" in res1["message"]

    # 2. Missing file (searched desktop)
    res2 = svc.rebuild_database("ghost_file_123.xlsx")
    assert res2["status"] == "error"
    assert "ไม่พบไฟล์" in res2["message"]
    assert "Desktop" in res2["message"]

    # 3. Missing 'วัสดุพื้นฐาน' worksheet
    wb_file = tmp_path / "no_target_sheet.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    wb.save(wb_file)

    res3 = svc.rebuild_database(str(wb_file))
    assert res3["status"] == "error"
    assert "ไม่มี Worksheet ชื่อ 'วัสดุพื้นฐาน'" in res3["message"]


def test_mcp_match_material_tool():
    """Verify match_material searches FAISS vector database and returns price details."""
    tool = mcp._local_provider._components["tool:match_material@"]
    res = tool.fn(material="เหล็กเส้นกลม SR24 RB6", record_type="material", top_k=3)

    assert res["status"] == "success"
    assert res["material_query"] == "เหล็กเส้นกลม SR24 RB6"
    assert res["total_matches"] > 0
    first = res["matches"][0]
    assert first["price_id"] == "MAT-011"
    assert first["unit"] == "กก."
    assert "unit_price" in first
    assert "similarity_score" in first
    assert "source_name" in first

    # Empty material error handling
    res_err = tool.fn(material="   ")
    assert res_err["status"] == "error"
    assert res_err["total_matches"] == 0


def test_price_service_search_prices():
    """Verify PriceService search_prices method still functions correctly."""
    svc = PriceService()
    res = svc.search_prices(query="เหล็ก DB12", record_type="material", max_results=3)

    assert res["status"] == "success"
    assert res["query"] == "เหล็ก DB12"
    assert res["total_results"] > 0
    first = res["results"][0]
    assert first["price_id"] == "MAT-008"
    assert first["unit"] == "กก."
    assert "unit_price" in first
    assert "currency" in first
    assert "source_name" in first
    assert "retrieval_method" in first

    # Also test invocation using material parameter
    res_mat = svc.search_prices(material="เหล็ก DB12", max_results=2)
    assert res_mat["status"] == "success"
    assert res_mat["total_results"] > 0


def test_price_service_get_price():
    """Verify PriceService get_price returns full record or not_found."""
    svc = PriceService()

    # Found case
    res = svc.get_price(price_id="MAT-008")
    assert res["status"] == "success"
    assert res["price_id"] == "MAT-008"
    rec = res["record"]
    assert rec["item_name"] == "เหล็กเส้นข้ออ้อย SD40 DB12 (งานเสา-คาน)"
    assert float(rec["unit_price"]) == 25.0
    assert rec["unit"] == "กก."
    assert rec["vat_included"] is False
    assert rec["transportation_included"] is False
    assert rec["original_excel_row"] == 12

    # Not found case
    res_nf = svc.get_price(price_id="INVALID-999")
    assert res_nf["status"] == "not_found"
    assert res_nf["record"] is None


def test_price_service_get_database_info():
    """Verify PriceService get_database_info returns metadata metrics."""
    svc = PriceService()
    res = svc.get_database_info()

    assert res["total_material_records"] >= 20
    assert res["total_labor_records"] >= 5
    assert res["total_records"] >= 25
    assert res["source_worksheet"] == "วัสดุพื้นฐาน"
    assert res["latest_price_date"] == "2026-07-01"
    assert len(res["source_file_hash"]) == 64
