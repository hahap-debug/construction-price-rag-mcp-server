"""MCP Tool Definitions for Construction Price Retrieval using FastMCP."""

from typing import Any, Literal
from fastmcp import FastMCP
from app.services.price_service import PriceService


def register_price_tools(mcp: FastMCP, service: PriceService | None = None) -> None:
    """Register construction price retrieval tools onto a FastMCP server instance.

    Registers 'match_material' for BIM-to-price matching and 'rebuild_price_database' for local DB rebuilding.

    Args:
        mcp: FastMCP server instance.
        service: PriceService business logic instance (initialized if None).
    """
    svc = service or PriceService()

    @mcp.tool(
        name="match_material",
        description=(
            "รับชื่อหรือสเปกวัสดุ (material) เช่น 'เหล็กเส้นกลม SR24 RB6', 'Concrete 240 ksc', 'อิฐมอญ' "
            "แล้วค้นหารายการที่ตรงกันใน Vector Database (FAISS) โดยใช้ Semantic Similarity "
            "และส่งคืนรายการที่ตรงกันพร้อมราคาจริง หน่วย วันที่ และแหล่งอ้างอิงจากฐานข้อมูล"
        ),
    )
    def match_material(
        material: str,
        record_type: Literal["material", "labor", "all"] = "material",
        unit: str | None = None,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> dict[str, Any]:
        """ค้นหารายการวัสดุที่ตรงกันใน Vector Database (FAISS) โดยรับชื่อหรือสเปกวัสดุ (material).

        Args:
            material: ชื่อหรือสเปกวัสดุที่ต้องการค้นหา เช่น 'เหล็กเส้นกลม SR24 RB6', 'คอนกรีตผสมเสร็จ 240 ksc', 'อิฐมอญ'
            record_type: ประเภทรายการ ('material' สำหรับวัสดุ, 'labor' สำหรับค่าแรง, 'all' สำหรับทั้งหมด)
            unit: กรองตามหน่วยนับ เช่น 'กก.', 'ถุง', 'ตร.ม.', 'ลบ.ม.', 'ก้อน'
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
            "อ่านข้อมูลราคาวัสดุและค่าแรงจาก Worksheet 'วัสดุพื้นฐาน' ของไฟล์ Excel ที่ระบุ "
            "รองรับการส่งชื่อไฟล์โดยตรง (ค้นหาใน Desktop, Downloads และ data/ ให้อัตโนมัติ) หรือ Full Path "
            "ตรวจเช็คความถูกต้องของไฟล์ Excel และทำ Clean Rebuild สร้างฐานข้อมูล SQLite + FAISS Index ใหม่ทั้งหมดทันที"
        ),
    )
    def rebuild_price_database(
        file_path: str = "data/Real_Price_Database_full.xlsx",
    ) -> dict[str, Any]:
        """สร้างฐานข้อมูลราคาใหม่ทั้งหมดจากไฟล์ Excel (Worksheet 'วัสดุพื้นฐาน').

        Args:
            file_path: ชื่อไฟล์หรือพาธไฟล์ Excel (เช่น 'Price.xlsx', 'C:/Users/.../Desktop/Price.xlsx')

        Returns:
            Structured dictionary สรุปผลการนำเข้าหรือข้อผิดพลาด
        """
        return svc.rebuild_database(file_path=file_path)
