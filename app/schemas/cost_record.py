"""Data models for CostRecord and Batch Price Matching, aligned with Rule-BOQ contracts."""

from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CostRecord(BaseModel):
    """Cost Record model matching Rule-BOQ's schema contract for downstream BOQ generation."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    cost_code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    boq_category: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    standard_labels: list[str] = Field(default_factory=list)
    material_keywords: list[str] = Field(default_factory=list)
    material_rate: Decimal = Decimal("0")
    labor_rate: Decimal = Decimal("0")
    equipment_rate: Decimal = Decimal("0")
    unit_rate: Decimal | None = None
    source: str = Field(min_length=1)
    price_date: str = Field(min_length=1)
    area: str | None = None
    currency: str = "THB"
    approved: bool = False
    database_version: str = "2026.11"

    @field_validator("material_rate", "labor_rate", "equipment_rate")
    @classmethod
    def non_negative_rate(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("cost rates must not be negative")
        return value


class BatchMatchItem(BaseModel):
    """Input query item for batch price matching."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    item_id: str | None = None
    query: str = Field(min_length=1)
    standard_label: str | None = None
    boq_category: str | None = None
    unit: str | None = None
    min_similarity: float = 0.0


class BatchMatchResultItem(BaseModel):
    """Result of a single item in a batch match operation."""

    model_config = ConfigDict(extra="ignore")

    item_id: str | None = None
    query: str
    status: Literal["matched", "requires_review", "no_match"]
    confidence_score: float
    cost_record: CostRecord | None = None
    material_match: dict[str, Any] | None = None
    labor_match: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class BatchMatchResponse(BaseModel):
    """Response payload for batch price matching."""

    status: Literal["success", "partial", "error"]
    total_queries: int
    matched_count: int
    review_count: int
    no_match_count: int
    items: list[BatchMatchResultItem]
