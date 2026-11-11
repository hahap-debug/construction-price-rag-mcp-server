"""Unit and Integration tests for FastMCP Tools and Service Layer."""

from server import mcp
from app.services.price_service import PriceService


def test_mcp_server_tool_registration():
    """Verify all 5 tools are registered on the FastMCP server."""
    provider = mcp._local_provider
    registered_keys = list(provider._components.keys())

    assert "tool:match_material@" in registered_keys
    assert "tool:rebuild_price_database@" in registered_keys
    assert "tool:get_database_status@" in registered_keys
    assert "tool:batch_match_prices@" in registered_keys
    assert "tool:export_boq_cost_records@" in registered_keys
    assert len(registered_keys) == 5


def test_mcp_rebuild_price_database_tool():
    """Verify rebuild_price_database cleans and rebuilds database correctly from price_database.xlsx."""
    tool = mcp._local_provider._components["tool:rebuild_price_database@"]
    res = tool.fn()
    assert res["status"] == "success"
    assert res["total_records"] >= 1000
    assert res["elements_imported"] >= 500
    assert res["materials_imported"] >= 400
    assert res["labor_imported"] >= 200
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

    # 2. Missing file (searched data/ folder)
    res2 = svc.rebuild_database("ghost_file_123.xlsx")
    assert res2["status"] == "error"
    assert "ไม่พบไฟล์" in res2["message"]
    assert "data" in res2["message"]

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
    assert first["price_id"] == "MAT-014"
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
    res = svc.get_price(price_id="MAT-014")
    assert res["status"] == "success"
    assert res["price_id"] == "MAT-014"
    rec = res["record"]
    assert "DB12" in rec["item_name"]
    assert float(rec["unit_price"]) == 25.0
    assert rec["unit"] in ("กก.", "kg")
    assert rec["normalized_unit"] == "กก."
    assert rec["vat_included"] is False
    assert rec["transportation_included"] is False

    # Not found case
    res_nf = svc.get_price(price_id="INVALID-999")
    assert res_nf["status"] == "not_found"
    assert res_nf["record"] is None


def test_price_service_get_database_info():
    """Verify PriceService get_database_info returns metadata metrics."""
    svc = PriceService()
    res = svc.get_database_info()

    assert res["total_element_records"] >= 500
    assert res["total_material_records"] >= 400
    assert res["total_labor_records"] >= 200
    assert res["total_records"] >= 1000
    assert "Element-based" in res["source_worksheet"]
    assert len(res["source_file_hash"]) == 64


def test_mcp_get_database_status_tool():
    """Verify get_database_status returns online status and counts."""
    tool = mcp._local_provider._components["tool:get_database_status@"]
    res = tool.fn()

    assert res["status"] == "online"
    assert res["total_element_records"] >= 500
    assert res["total_material_records"] >= 400
    assert res["total_labor_records"] >= 200
    assert res["total_records"] >= 1000
    assert res["vector_index_size"] >= 1000


def test_mcp_match_bim_element_tool():
    """Verify match_material matches Revit/BIM structural element queries."""
    tool = mcp._local_provider._components["tool:match_material@"]
    res = tool.fn(material="ST_202A_RCColumn_Rectangular C12", top_k=3)

    assert res["status"] == "success"
    assert res["total_matches"] > 0
    first = res["matches"][0]
    assert first["record_type"] == "element"
    assert "C12" in first["item_name"]
    assert "unit_price" in first
    assert float(first["unit_price"]) > 0


def test_mcp_batch_match_prices_tool():
    """Verify batch_match_prices tool processes multiple BIM items in parallel."""
    tool = mcp._local_provider._components["tool:batch_match_prices@"]
    batch_input = [
        {"id": "JOB-01", "query": "คอนกรีต 240 ksc", "unit": "ลบ.ม.", "standard_label": "RC_COLUMN"},
        {"id": "JOB-02", "query": "เหล็กข้ออ้อย DB12", "unit": "กก.", "standard_label": "REBAR"},
        {"id": "JOB-03", "query": "ค่าแรงเทคอนกรีต", "unit": "ลบ.ม.", "standard_label": "CONCRETE_POURING"},
    ]
    res = tool.fn(items=batch_input)

    assert res["status"] in ("success", "partial")
    assert res["total_queries"] == 3
    assert len(res["items"]) == 3

    # Check job 1
    job1 = res["items"][0]
    assert job1["item_id"] == "JOB-01"
    assert job1["confidence_score"] > 0.0
    assert job1["cost_record"] is not None
    assert float(job1["cost_record"]["material_rate"]) > 0 or float(job1["cost_record"]["labor_rate"]) > 0

    # Check job 2
    job2 = res["items"][1]
    assert job2["item_id"] == "JOB-02"
    assert "REBAR" in job2["cost_record"]["standard_labels"]


def test_mcp_export_boq_cost_records_tool():
    """Verify export_boq_cost_records outputs valid CostRecord schema for Rule-BOQ."""
    tool = mcp._local_provider._components["tool:export_boq_cost_records@"]
    res = tool.fn(limit=5)

    assert isinstance(res, list)
    assert len(res) == 5
    first = res[0]
    assert "cost_code" in first
    assert "description" in first
    assert "unit" in first
    assert "material_rate" in first
    assert "labor_rate" in first
    assert first["approved"] is False


def test_price_service_match_composite_rate():
    """Verify dynamic composite rate assembly for material + labor."""
    svc = PriceService()
    res = svc.match_composite_rate(
        query="คอนกรีตเสา ค.ส.ล. 240 ksc",
        unit="ลบ.ม.",
        standard_label="RC_COLUMN",
    )

    assert res["status"] in ("matched", "requires_review")
    assert res["confidence_score"] > 0.0
    cost_rec = res["cost_record"]
    assert cost_rec["unit"] == "ลบ.ม."
    assert float(cost_rec["unit_rate"]) > 0

