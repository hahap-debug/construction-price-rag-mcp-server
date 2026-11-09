"""Unit tests for Data Normalizer."""

from datetime import date
from decimal import Decimal
import pytest
from app.ingestion.data_normalizer import DataNormalizer


def test_parse_price_valid_and_commas():
    """Verify numeric string and comma removal."""
    assert DataNormalizer.parse_price(110.0) == Decimal("110.0")
    assert DataNormalizer.parse_price("24.5") == Decimal("24.5")
    assert DataNormalizer.parse_price("2,100.00") == Decimal("2100.00")
    assert DataNormalizer.parse_price(2000) == Decimal("2000")


def test_parse_price_invalid_raises():
    """Verify invalid and negative prices raise ValueError."""
    with pytest.raises(ValueError):
        DataNormalizer.parse_price(None)

    with pytest.raises(ValueError):
        DataNormalizer.parse_price("")

    with pytest.raises(ValueError):
        DataNormalizer.parse_price("invalid_number")

    with pytest.raises(ValueError):
        DataNormalizer.parse_price(-10.0)


def test_parse_market_range():
    """Verify market price range parsing formats."""
    # Min - Max format
    min_p, max_p = DataNormalizer.parse_market_range("90 - 150")
    assert min_p == Decimal("90")
    assert max_p == Decimal("150")

    # Range with commas
    min_p, max_p = DataNormalizer.parse_market_range("1,900 - 2,325")
    assert min_p == Decimal("1900")
    assert max_p == Decimal("2325")

    # Decimal range
    min_p, max_p = DataNormalizer.parse_market_range("24.8 - 25.3")
    assert min_p == Decimal("24.8")
    assert max_p == Decimal("25.3")

    # Approx format
    min_p, max_p = DataNormalizer.parse_market_range("~26.0")
    assert min_p == Decimal("26.0")
    assert max_p == Decimal("26.0")

    # Empty
    assert DataNormalizer.parse_market_range(None) == (None, None)
    assert DataNormalizer.parse_market_range("") == (None, None)


def test_unit_normalization_and_aliases():
    """Verify unit normalization and query alias mapping."""
    assert DataNormalizer.normalize_unit("ตร.ม. (ที่ใช้)") == "ตร.ม."
    assert DataNormalizer.normalize_unit("ลบ.ม. (คิว)") == "ลบ.ม."
    assert DataNormalizer.normalize_unit("กก.") == "กก."
    assert DataNormalizer.normalize_unit("ถุง") == "ถุง"

    # Query alias resolution
    assert DataNormalizer.resolve_query_unit("kg") == "กก."
    assert DataNormalizer.resolve_query_unit("กิโลกรัม") == "กก."
    assert DataNormalizer.resolve_query_unit("ตรม") == "ตร.ม."
    assert DataNormalizer.resolve_query_unit("sqm") == "ตร.ม."
    assert DataNormalizer.resolve_query_unit("m3") == "ลบ.ม."
    assert DataNormalizer.resolve_query_unit("คิว") == "ลบ.ม."


def test_date_parsing_buddhist_era():
    """Verify conversion from Thai BE year (2569) to CE (2026)."""
    d = DataNormalizer.parse_price_date("อ้างอิงราคาตลาดจริง ณ กรกฎาคม 2569")
    assert d == date(2026, 7, 1)

    d2 = DataNormalizer.parse_price_date("อัปเดต ก.ค. 2569")
    assert d2 == date(2026, 7, 1)


def test_extract_sources_and_urls():
    """Verify source and domain extraction without fabrication."""
    src, url = DataNormalizer.extract_sources_and_urls(
        "เฉลี่ยจากราคาขายปลีกหลายยี่ห้อ (buildmate.co.th, hiachet.com) ก.ค. 2569"
    )
    assert url == "https://buildmate.co.th"
    assert src == "Buildmate"

    src2, url2 = DataNormalizer.extract_sources_and_urls(
        "SteelLead.com ราคาส่งโรงงาน ไม่รวม VAT อัปเดต ก.ค. 2569"
    )
    assert url2 == "https://SteelLead.com"
    assert src2 == "SteelLead"
