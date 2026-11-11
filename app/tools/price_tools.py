"""MCP Tool Definitions for Construction Price Retrieval using FastMCP."""

from typing import Any, Literal
from fastmcp import FastMCP
from app.services.price_service import PriceService


def register_price_tools(mcp: FastMCP, service: PriceService | None = None) -> None:
    """Register construction price retrieval tools onto a FastMCP server instance.

    Registers 'match_material' for BIM-to-price matching, 'rebuild_price_database' for local DB rebuilding,
    and 'get_database_status' for inspecting database health and record statistics.

    Args:
        mcp: FastMCP server instance.
        service: PriceService business logic instance (initialized if None).
    """
    svc = service or PriceService()

    @mcp.tool(
        name="match_material",
        description=(
            "รับชื่อองค์ประกอบอาคาร BIM (Element เช่น ST_202A_RCColumn_Rectangular C12, ST_101A_RCBeam, Precast Pile, เสาเข็ม I-22, Monolithic Stair), "
            "สเปกวัสดุก่อสร้าง (Material เช่น เหล็กข้ออ้อย DB12, ปูนซีเมนต์ปอร์ตแลนด์, คอนกรีต 240 ksc), "
            "หรือค่าแรงงาน (Labor เช่น ค่าแรงก่ออิฐ, ผูกเหล็ก, ทดสอบความสมบูรณ์เสาเข็ม Seismic Test) "
            "แล้วค้นหารายการที่ตรงกันใน Vector Database (FAISS) โดยใช้ Semantic Similarity "
            "และส่งคืนรายการที่ตรงกันพร้อมราคาจริง หน่วย วันที่ และแหล่งอ้างอิงจากฐานข้อมูล"
        ),
    )
    def match_material(
        material: str,
        record_type: Literal["element", "material", "labor", "all"] = "all",
        unit: str | None = None,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> dict[str, Any]:
        """ค้นหารายการชิ้นส่วน BIM, วัสดุ หรือค่าแรงที่ตรงกันใน Vector Database (FAISS).

        Args:
            material: ชื่อหรือสเปกที่ต้องการค้นหา เช่น 'ST_202A_RCColumn_Rectangular C12', 'เหล็ก DB12', 'เสาเข็ม I-22', 'ค่าแรงผูกเหล็ก'
            record_type: ประเภทรายการ ('element' สำหรับชิ้นส่วน BIM, 'material' สำหรับวัสดุ, 'labor' สำหรับค่าแรง, 'all' สำหรับทั้งหมด)
            unit: กรองตามหน่วยนับ เช่น 'ต้น', 'ลบ.ม.', 'ตร.ม.', 'กก.', 'ถุง', 'จุด'
            top_k: จำนวนผลลัพธ์สูงสุดที่ต้องการ (ค่าเริ่มต้น: 5)
            min_similarity: ค่าความเหมือนขั้นต่ำ 0.0 ถึง 1.0 (ค่าเริ่มต้น: 0.0)

        Returns:
            Structured dictionary ประกอบด้วย status, material_query, total_matches, และ matches พร้อมราคาและแหล่งอ้างอิง
        """
        return svc.match_material(
            material=material,
            record_type=record_type,
            unit=unit,
            top_k=top_k,
            min_similarity=min_similarity,
        )

    @mcp.tool(
        name="batch_match_prices",
        description=(
            "รับรายการคำขอค้นหาราคาเป็นชุด (Batch) สำหรับชิ้นส่วน BIM และรายการปริมาณงาน (QTO) จาก Rule-BOQ หรือ Agent "
            "ค้นหาด้วย Vector Matrix Search ในมิติวัสดุและมิติค่าแรงพร้อมกันในเสี้ยววินาที "
            "ส่งคืนผลลัพธ์พร้อม material_rate, labor_rate, unit_rate, confidence_score และโครงสร้าง CostRecord"
        ),
    )
    def batch_match_prices(
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """จับคู่ราคาเป็นชุด (Batch Matching) สำหรับงาน BIM ทั้งโมเดล/ทั้งชั้น.

        Args:
            items: รายการ dict เช่น [{'id': '1', 'query': 'คอนกรีตเสา C12 240 ksc', 'unit': 'm3'}]

        Returns:
            Structured dictionary ประกอบด้วยผลการจับคู่แยกรายชิ้น ค่าความมั่นใจ และ CostRecord
        """
        return svc.batch_match_prices(items=items)

    @mcp.tool(
        name="export_boq_cost_records",
        description=(
            "ส่งออกข้อมูลราคาที่อยู่ในฐานข้อมูลออกมาเป็นชุด Object ชนิด CostRecord ตามสัญญาของ Rule-BOQ "
            "เพื่อให้ฟังก์ชัน generate_boq ของ Rule-BOQ นำไปใช้คำนวณต้นทุนต่อได้ทันที"
        ),
    )
    def export_boq_cost_records(
        standard_labels: list[str] | None = None,
        approved_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """ส่งออก CostRecord สำหรับป้อนเข้า Rule-BOQ.

        Args:
            standard_labels: รายการป้ายมาตรฐานที่ต้องการกรอง เช่น ['RC_COLUMN', 'REBAR']
            approved_only: กรองเฉพาะรายการที่ได้รับการอนุมัติแล้ว
            limit: จำนวนรายการสูงสุดที่ต้องการส่งออก (ค่าเริ่มต้น: 100)

        Returns:
            List ของ CostRecord objects พร้อมใช้กับ Rule-BOQ
        """
        return svc.export_boq_cost_records(
            standard_labels=standard_labels,
            approved_only=approved_only,
            limit=limit,
        )

    @mcp.tool(
        name="rebuild_price_database",
        description=(
            "อ่านข้อมูลราคาชิ้นส่วนอาคาร (Element), วัสดุก่อสร้าง (Material) และค่าแรงงาน (Labor) จากไฟล์ Excel ในโฟลเดอร์ data/ "
            "ตรวจจับไฟล์ .xlsx ในโฟลเดอร์ data/ อัตโนมัติแบบไดนามิก (หรือระบุชื่อไฟล์เจาะจงได้) "
            "ทำการลบข้อมูลเดิมออกให้หมดจดก่อน แล้วสร้างฐานข้อมูล SQLite + FAISS Vector Index ใหม่ลงใน data/price_database/"
        ),
    )
    def rebuild_price_database(
        file_path: str = "price_database.xlsx",
    ) -> dict[str, Any]:
        """สร้างฐานข้อมูลราคาใหม่ทั้งหมดจากไฟล์ Excel ใน data/ (ลบข้อมูลเก่าก่อนสร้างใหม่เสมอ).

        Args:
            file_path: ชื่อไฟล์หรือพาธไฟล์ Excel (ค่าเริ่มต้น: ตรวจจับไฟล์ .xlsx ใน data/ อัตโนมัติ)

        Returns:
            Structured dictionary สรุปผลการนำเข้าหรือข้อผิดพลาด
        """
        return svc.rebuild_database(file_path=file_path)

    @mcp.tool(
        name="get_database_status",
        description=(
            "ตรวจสอบสถานะและสถิติของฐานข้อมูลราคาปัจจุบัน "
            "แสดงจำนวนรายการชิ้นส่วน BIM (Element), วัสดุก่อสร้าง (Material), ค่าแรงงาน (Labor), "
            "ขนาด FAISS Vector Index, แหล่งไฟล์ Excel ต้นทาง และพาธจัดเก็บข้อมูล SQLite/FAISS"
        ),
    )
    def get_database_status() -> dict[str, Any]:
        """ตรวจสอบสถานะและสถิติภาพรวมของฐานข้อมูลราคาและ Vector Index."""
        from app.config import settings

        db_info = svc.get_database_info()
        vector_count = svc.vector_db.count() if svc.vector_db else 0

        return {
            "status": "online",
            "database_name": db_info.get("database_name"),
            "storage_location": "Desktop (price_database)" if settings.use_desktop_storage else "Local Project (data/price_database)",
            "sqlite_path": str(svc.sqlite_db.db_path),
            "faiss_path": str(svc.vector_db.persist_directory) if svc.vector_db else None,
            "source_excel_file": db_info.get("source_excel_file"),
            "source_worksheet": db_info.get("source_worksheet"),
            "total_element_records": db_info.get("total_element_records", 0),
            "total_material_records": db_info.get("total_material_records", 0),
            "total_labor_records": db_info.get("total_labor_records", 0),
            "total_records": db_info.get("total_records", 0),
            "vector_index_size": vector_count,
            "latest_price_date": db_info.get("latest_price_date"),
            "import_timestamp": db_info.get("import_timestamp"),
        }
