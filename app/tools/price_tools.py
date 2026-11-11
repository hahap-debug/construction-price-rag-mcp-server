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
        name="rebuild_price_database",
        description=(
            "อ่านข้อมูลราคาชิ้นส่วนอาคาร (Element), วัสดุก่อสร้าง (Material) และค่าแรงงาน (Labor) จากไฟล์ Excel "
            "รองรับทั้งรูปแบบ 3 Worksheet ('Element-based', 'Material-based', 'ค่าแรงงาน') และรูปแบบเดี่ยว 'วัสดุพื้นฐาน' "
            "ค้นหาไฟล์ใน Desktop, Downloads และ data/ ให้อัตโนมัติ หรือระบุ Full Path "
            "ตรวจเช็คความถูกต้องและทำ Clean Rebuild สร้างฐานข้อมูล SQLite + FAISS Vector Index ใหม่ทั้งหมดทันที"
        ),
    )
    def rebuild_price_database(
        file_path: str = "price_database.xlsx",
    ) -> dict[str, Any]:
        """สร้างฐานข้อมูลราคาใหม่ทั้งหมดจากไฟล์ Excel (3 Worksheet หรือ 'วัสดุพื้นฐาน').

        Args:
            file_path: ชื่อไฟล์หรือพาธไฟล์ Excel (ค่าเริ่มต้น: 'price_database.xlsx')

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
            "storage_location": "Desktop (price_database)" if settings.use_desktop_storage else "Local (data/)",
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
