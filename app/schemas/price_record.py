"""Pydantic Schemas for Construction Price Records and MCP Tool Payloads."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class PriceRecord(BaseModel):
    """Standard Data Schema for Construction Material and Labor Price Records."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    price_id: str = Field(
        ...,
        description="Deterministic unique identifier (e.g., MAT-001, LAB-001)",
    )
    record_type: Literal["material", "labor"] = Field(
        ...,
        description="Classification: material or labor",
    )
    item_name: str = Field(
        ...,
        description="Original name of the item from the source file",
    )
    normalized_item_name: str = Field(
        ...,
        description="Standardized name for exact and fuzzy matching",
    )
    category: str | None = Field(
        default=None,
        description="Category classification if explicitly present in source data",
    )
    description: str | None = Field(
        default=None,
        description="Additional technical description or usage context",
    )
    unit: str = Field(
        ...,
        description="Original measurement unit from the source file",
    )
    normalized_unit: str = Field(
        ...,
        description="Standardized measurement unit (e.g., กก., ตร.ม., ลบ.ม., ถุง)",
    )
    unit_price: Decimal = Field(
        ...,
        description="Unit price in Thai Baht (exact Decimal)",
    )
    market_min: Decimal | None = Field(
        default=None,
        description="Minimum market range price in Thai Baht",
    )
    market_max: Decimal | None = Field(
        default=None,
        description="Maximum market range price in Thai Baht",
    )
    currency: str = Field(
        default="THB",
        description="Currency code (defaults to THB)",
    )
    price_date: date | None = Field(
        default=None,
        description="Effective date of the price record",
    )
    source_name: str | None = Field(
        default=None,
        description="Primary publisher or source name (e.g. SteelLead, Buildmate)",
    )
    source_url: str | None = Field(
        default=None,
        description="Source reference URL if available",
    )
    source_note: str | None = Field(
        default=None,
        description="Raw reference text and notes from source",
    )
    vat_included: bool | None = Field(
        default=False,
        description="Whether VAT (7%) is included in the unit price",
    )
    transportation_included: bool | None = Field(
        default=False,
        description="Whether transportation cost is included in the unit price",
    )
    original_excel_row: int = Field(
        ...,
        description="Source row index in Excel for full traceability",
    )
    raw_source_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Exact raw cell values extracted from source row",
    )
    imported_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the record was ingested into the database",
    )


class SearchResultItem(BaseModel):
    """Result item returned by retrieval engine with ranking metadata."""

    price_id: str
    record_type: Literal["material", "labor"]
    item_name: str
    unit: str
    unit_price: Decimal
    market_min: Decimal | None = None
    market_max: Decimal | None = None
    currency: str = "THB"
    price_date: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    source_note: str | None = None
    vat_included: bool | None = False
    transportation_included: bool | None = False
    retrieval_method: str = Field(
        ...,
        description="Method that retrieved this result: exact, fuzzy, semantic, or hybrid",
    )
    confidence_score: float = Field(
        ...,
        description="Retrieval confidence or ranking fusion score",
    )


class SearchResponse(BaseModel):
    """Structured response for search_construction_prices MCP tool."""

    status: Literal["success", "no_results", "error"]
    query: str
    total_results: int
    results: list[SearchResultItem]
    message: str | None = None


class PriceRecordResponse(BaseModel):
    """Structured response for get_construction_price MCP tool."""

    status: Literal["success", "not_found", "error"]
    price_id: str
    record: dict[str, Any] | None = None
    message: str | None = None


class DatabaseInfo(BaseModel):
    """Structured response for get_price_database_info MCP tool."""

    database_name: str
    source_excel_file: str
    source_worksheet: str
    source_file_hash: str
    total_material_records: int
    total_labor_records: int
    total_records: int
    latest_price_date: str | None
    import_timestamp: str


class ImportReport(BaseModel):
    """Report generated after Excel ingestion pipeline executes."""

    total_rows_read: int
    materials_imported: int
    labor_imported: int
    records_created: int
    records_updated: int
    rows_skipped: int
    issues_found: list[str] = Field(default_factory=list)
    source_hash: str
    status: Literal["success", "partial", "failed"]
