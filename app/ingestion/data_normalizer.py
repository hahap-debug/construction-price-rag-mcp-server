"""Data Normalizer for Construction Price Ingestion."""

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any


class DataNormalizer:
    """Normalizes raw Excel values into standardized typed structures."""

    # Month mapping for Thai Buddhist era dates
    THAI_MONTHS = {
        "ม.ค.": 1, "มกราคม": 1,
        "ก.พ.": 2, "กุมภาพันธ์": 2,
        "มี.ค.": 3, "มีนาคม": 3,
        "เม.ย.": 4, "เมษายน": 4,
        "พ.ค.": 5, "พฤษภาคม": 5,
        "มิ.ย.": 6, "มิถุนายน": 6,
        "ก.ค.": 7, "กรกฎาคม": 7,
        "ส.ค.": 8, "สิงหาคม": 8,
        "ก.ย.": 9, "กันยายน": 9,
        "ต.ค.": 10, "ตุลาคม": 10,
        "พ.ย.": 11, "พฤศจิกายน": 11,
        "ธ.ค.": 12, "ธันวาคม": 12,
    }

    # Unit standardization mapping
    UNIT_NORMALIZATION = {
        "ถุง": "ถุง",
        "ตร.ม. (ที่ใช้)": "ตร.ม.",
        "ตร.ม. (ผิวสัมผัส)": "ตร.ม.",
        "ตร.ม.": "ตร.ม.",
        "ตรม": "ตร.ม.",
        "ตร.ม": "ตร.ม.",
        "ตารางเมตร": "ตร.ม.",
        "m2": "ตร.ม.",
        "sqm": "ตร.ม.",
        "ลบ.ม. (คิว)": "ลบ.ม.",
        "ลบ.ม.": "ลบ.ม.",
        "ลบม": "ลบ.ม.",
        "ลบ.ม": "ลบ.ม.",
        "ลูกบาศก์เมตร": "ลบ.ม.",
        "คิว": "ลบ.ม.",
        "m3": "ลบ.ม.",
        "m³": "ลบ.ม.",
        "cum": "ลบ.ม.",
        "กก.": "กก.",
        "กก": "กก.",
        "กิโล": "กก.",
        "กิโลกรัม": "กก.",
        "kg": "กก.",
        "kg.": "กก.",
        "ก้อน": "ก้อน",
        "ต้น": "ต้น",
        "ชุด": "ชุด",
        "บาน": "บาน",
        "เครื่อง": "เครื่อง",
        "เมตร": "ม.",
        "ม.": "ม.",
        "ม": "ม.",
        "m": "ม.",
        "meter": "ม.",
        "จุด": "จุด",
        "ตัน": "ตัน",
        "ton": "ตัน",
        "กล่อง": "กล่อง",
        "ท่อน": "ท่อน",
        "เที่ยว": "เที่ยว",
    }

    # Query unit alias mapping (for search filtering)
    UNIT_ALIASES = {
        "กก": "กก.",
        "กก.": "กก.",
        "กิโล": "กก.",
        "กิโลกรัม": "กก.",
        "kg": "กก.",
        "ตรม": "ตร.ม.",
        "ตร.ม": "ตร.ม.",
        "ตร.ม.": "ตร.ม.",
        "ตารางเมตร": "ตร.ม.",
        "m2": "ตร.ม.",
        "sqm": "ตร.ม.",
        "ลบม": "ลบ.ม.",
        "ลบ.ม": "ลบ.ม.",
        "ลบ.ม.": "ลบ.ม.",
        "ลูกบาศก์เมตร": "ลบ.ม.",
        "คิว": "ลบ.ม.",
        "m3": "ลบ.ม.",
        "m³": "ลบ.ม.",
        "cum": "ลบ.ม.",
        "ถุง": "ถุง",
        "bag": "ถุง",
        "ก้อน": "ก้อน",
        "block": "ก้อน",
        "ต้น": "ต้น",
        "ชุด": "ชุด",
        "บาน": "บาน",
        "เครื่อง": "เครื่อง",
        "เมตร": "ม.",
        "ม": "ม.",
        "ม.": "ม.",
        "m": "ม.",
        "meter": "ม.",
        "จุด": "จุด",
        "ตัน": "ตัน",
        "ton": "ตัน",
        "กล่อง": "กล่อง",
        "ท่อน": "ท่อน",
        "เที่ยว": "เที่ยว",
    }

    @classmethod
    def normalize_text(cls, text: str | None) -> str:
        """Standardize text by stripping whitespace, normalizing spaces and case."""
        if not text:
            return ""
        s = str(text).strip()
        # Collapse multiple spaces
        s = re.sub(r"\s+", " ", s)
        return s

    @classmethod
    def normalize_unit(cls, raw_unit: str | None) -> str:
        """Map raw unit string to standard Thai construction measurement unit."""
        if not raw_unit:
            return ""
        clean = cls.normalize_text(raw_unit)
        return cls.UNIT_NORMALIZATION.get(clean, clean)

    @classmethod
    def resolve_query_unit(cls, query_unit: str | None) -> str | None:
        """Resolve a user-provided unit query or alias into standard unit."""
        if not query_unit:
            return None
        clean = query_unit.strip().lower()
        return cls.UNIT_ALIASES.get(clean, clean)

    @classmethod
    def parse_price(cls, raw_price: Any) -> Decimal:
        """Parse raw price value into a high-precision Decimal.
        
        Raises ValueError if the price is invalid or non-numeric.
        """
        if raw_price is None or raw_price == "":
            raise ValueError("Price is missing or empty")

        clean_str = str(raw_price).replace(",", "").strip()
        try:
            val = Decimal(clean_str)
            if val < 0:
                raise ValueError(f"Price cannot be negative: {raw_price}")
            return val
        except InvalidOperation as e:
            raise ValueError(f"Unable to convert price '{raw_price}' to Decimal") from e

    @classmethod
    def parse_market_range(cls, raw_range: Any) -> tuple[Decimal | None, Decimal | None]:
        """Parse market price range string like '90 - 150', '~26.0', or '1,900 - 2,325'."""
        if not raw_range:
            return None, None

        s = str(raw_range).replace(",", "").strip()
        if not s:
            return None, None

        # Format ~26.0
        if s.startswith("~"):
            val_str = s[1:].strip()
            try:
                val = Decimal(val_str)
                return val, val
            except InvalidOperation:
                return None, None

        # Format min - max
        if "-" in s:
            parts = s.split("-")
            if len(parts) == 2:
                try:
                    p_min = Decimal(parts[0].strip())
                    p_max = Decimal(parts[1].strip())
                    return p_min, p_max
                except InvalidOperation:
                    return None, None

        # Single number fallback
        try:
            val = Decimal(s)
            return val, val
        except InvalidOperation:
            return None, None

    @classmethod
    def parse_price_date(cls, note_text: str | None, default_date: date | None = None) -> date | None:
        """Extract effective date from note or header text, converting BE to CE year."""
        if default_date is None:
            default_date = date(2026, 7, 1)  # July 2569 BE

        if not note_text:
            return default_date

        text = str(note_text)
        # Search for 4-digit BE year (e.g. 2569)
        year_match = re.search(r"25[5-7][0-9]", text)
        year = int(year_match.group(0)) - 543 if year_match else default_date.year

        # Search for month
        month = default_date.month
        for m_name, m_num in cls.THAI_MONTHS.items():
            if m_name in text:
                month = m_num
                break

        try:
            return date(year, month, 1)
        except ValueError:
            return default_date

    @classmethod
    def extract_sources_and_urls(cls, note_text: str | None) -> tuple[str | None, str | None]:
        """Extract primary domain/URL and source name from note text without fabrication."""
        if not note_text:
            return None, None

        text = str(note_text)
        # Find domain patterns e.g. buildmate.co.th, hiachet.com, ratanon.com, SteelLead.com
        domains = re.findall(r"([a-zA-Z0-9_\-]+\.(?:com|co\.th|net|org))", text)
        url = f"https://{domains[0]}" if domains else None

        # Known source names
        known_sources = [
            "SteelLead", "Buildmate", "OneStockHome", "CPAC", "Pantip",
            "itdang2009", "thaisoung", "จึงรุ่งซีเมนต์บล็อค", "กรมการค้าภายใน"
        ]
        found_source = None
        for ks in known_sources:
            if ks.lower() in text.lower():
                found_source = ks
                break

        if not found_source and domains:
            found_source = domains[0]

        return found_source, url

    @classmethod
    def extract_bim_metadata(cls, item_name: str | None) -> dict[str, str | None]:
        """Extract BIM Family, Type, and Category from structured element names.

        Example:
          'คอนกรีตเสา (RC Columns) : ST_202A_RCColumn_Rectangular - C12_350x1950mm / Structural Element [Structural Columns]'
          -> category: 'Structural Columns'
          -> bim_family: 'ST_202A_RCColumn_Rectangular'
          -> bim_type: 'C12_350x1950mm'
        """
        result: dict[str, str | None] = {
            "bim_family": None,
            "bim_type": None,
            "bim_category": None,
        }
        if not item_name:
            return result

        name_str = str(item_name).strip()

        # Check for category tag [Category] at end
        cat_match = re.search(r"\[(.*?)\]\s*$", name_str)
        if cat_match:
            result["bim_category"] = cat_match.group(1).strip()

        # Check for pattern ': Family - Type /' or ': Family - Type'
        match = re.search(r":\s*([^-]+?)\s*-\s*([^/]+?)(?:\s*/|$)", name_str)
        if match:
            result["bim_family"] = match.group(1).strip()
            result["bim_type"] = match.group(2).strip()

        return result
