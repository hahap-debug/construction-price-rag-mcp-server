"""Data Validator for Construction Price Records."""

from typing import Any
from app.schemas.price_record import PriceRecord


class ValidationError(Exception):
    """Raised when data fails validation rules."""
    pass


class DataValidator:
    """Validates raw and normalized construction price records."""

    @classmethod
    def validate_record_dict(cls, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate record dictionary before or during model instantiation.

        Returns:
            Tuple of (is_valid, list of error messages).
        """
        errors = []

        if not data.get("price_id"):
            errors.append("price_id is required and cannot be empty")

        if data.get("record_type") not in ("element", "material", "labor"):
            errors.append(f"Invalid record_type: '{data.get('record_type')}'. Must be 'element', 'material', or 'labor'")

        if not data.get("item_name") or not str(data.get("item_name")).strip():
            errors.append("item_name is required and cannot be blank")

        if not data.get("unit") or not str(data.get("unit")).strip():
            errors.append("unit is required and cannot be blank")

        price = data.get("unit_price")
        if price is None:
            errors.append("unit_price is required")
        else:
            try:
                if price <= 0:
                    errors.append(f"unit_price must be greater than zero, got {price}")
            except TypeError:
                errors.append(f"unit_price is not comparable numeric: {price}")

        min_p = data.get("market_min")
        max_p = data.get("market_max")
        if min_p is not None and max_p is not None:
            if min_p > max_p:
                errors.append(f"market_min ({min_p}) cannot be greater than market_max ({max_p})")

        return len(errors) == 0, errors

    @classmethod
    def validate_and_create_model(cls, data: dict[str, Any]) -> PriceRecord:
        """Validate and create a validated PriceRecord Pydantic instance."""
        is_valid, errors = cls.validate_record_dict(data)
        if not is_valid:
            raise ValidationError("; ".join(errors))

        try:
            return PriceRecord(**data)
        except Exception as e:
            raise ValidationError(f"Pydantic validation failed: {e}") from e
