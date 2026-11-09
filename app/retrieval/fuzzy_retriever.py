"""Fuzzy Search Retriever using RapidFuzz with Construction Specification Guardrails."""

import re
from typing import Any
from rapidfuzz import fuzz

from app.config import logger
from app.schemas.price_record import PriceRecord


class FuzzyRetriever:
    """Performs approximate string matching with domain-specific specification conflict guards."""

    # Patterns for key material specifications that must not be confused
    SPEC_PATTERNS = [
        r"\bDB\s*12\b", r"\bDB\s*16\b", r"\bDB\s*20\b", r"\bDB\s*25\b",
        r"\bRB\s*6\b", r"\bRB\s*9\b",
        r"\bSD\s*40\b", r"\bSD\s*50\b",
        r"\bSR\s*24\b",
        r"\b210\s*-\s*240\b", r"\b280\b",
        r"\b50\s*กก\b",
        r"\b7\s*ซม\b",
        r"\b9\s*มม\b",
    ]

    # Conversational filler words
    FILLER_WORDS = [
        r"ราคาเท่าไร", r"ราคาเท่าไหร่", r"ราคา", r"เท่าไร", r"เท่าไหร่",
        r"ขอราคา", r"ขอทราบราคา", r"กี่บาท", r"บาท", r"ขอ", r"ต้องการ",
        r"ช่วยหา", r"ค้นหา", r"หารายการ", r"รายการ", r"ต่อหน่วย", r"ทำ",
    ]

    # Key construction usage keywords that provide high-signal intent
    USAGE_KEYWORDS = [
        "ปลอกเสา", "ปลอกคาน", "ข้ออ้อย", "คอนกรีต", "ก่ออิฐ",
        "ฉาบปูน", "เทพื้น", "ปูกระเบื้อง", "ผูกเหล็ก", "ไม้แบบ",
        "ยิปซั่ม", "อิฐมอญ", "อิฐบล็อก", "ทรายหยาบ", "ทรายละเอียด",
        "หินเกล็ด", "ปูนซีเมนต์", "ลวดผูกเหล็ก",
    ]

    def __init__(self, similarity_threshold: float = 0.35):
        self.threshold = similarity_threshold

    @classmethod
    def clean_query_core(cls, query: str) -> str:
        """Strip conversational filler words while strictly preserving material keywords."""
        q = query.strip()
        for pattern in cls.FILLER_WORDS:
            q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", q).strip()

    @classmethod
    def extract_specs(cls, text: str) -> set[str]:
        """Extract standardized specification tokens from a text string."""
        specs = set()
        clean = text.upper()
        for pat in cls.SPEC_PATTERNS:
            match = re.search(pat, clean, flags=re.IGNORECASE)
            if match:
                token = re.sub(r"\s+", "", match.group(0).upper())
                specs.add(token)
        return specs

    def has_spec_conflict(self, query_specs: set[str], item_specs: set[str]) -> bool:
        """Check if query specifies dimensions/grades that the item does not satisfy.
        
        Example: Query specifies DB12, but item is DB16 or does not have DB12.
        """
        # Rebar diameter conflicts (DB12, DB16, DB20, DB25)
        db_query = {s for s in query_specs if s.startswith("DB")}
        db_item = {s for s in item_specs if s.startswith("DB")}
        if db_query and not (db_query & db_item):
            return True

        # Round bar diameter conflicts (RB6, RB9)
        rb_query = {s for s in query_specs if s.startswith("RB")}
        rb_item = {s for s in item_specs if s.startswith("RB")}
        if rb_query and not (rb_query & rb_item):
            return True

        # Concrete strength conflicts (210-240, 280)
        conc_query = {s for s in query_specs if s in ("210-240", "280")}
        conc_item = {s for s in item_specs if s in ("210-240", "280")}
        if conc_query and not (conc_query & conc_item):
            return True

        return False

    def search(
        self,
        query: str,
        records: list[PriceRecord],
        record_type: str | None = None,
        unit: str | None = None,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Find approximate matches using RapidFuzz, boosting usage keywords and penalizing spec conflicts."""
        min_score = threshold if threshold is not None else self.threshold
        q_raw = query.strip()
        q_core = self.clean_query_core(query)
        if not q_raw and not q_core:
            return []

        q_specs = self.extract_specs(q_raw)
        candidates: list[dict[str, Any]] = []

        for r in records:
            if record_type and record_type != "all" and r.record_type != record_type:
                continue
            if unit and r.normalized_unit != unit and r.unit != unit:
                continue

            item_text = r.item_name
            # Evaluate using both raw query and core stripped query
            w_score1 = fuzz.WRatio(q_raw, item_text) / 100.0
            w_score2 = fuzz.WRatio(q_core, item_text) / 100.0 if q_core else 0.0
            ts_score = fuzz.token_set_ratio(q_core or q_raw, item_text) / 100.0
            raw_score = max(w_score1, w_score2, ts_score)

            # Check specific high-signal usage keywords
            for kw in self.USAGE_KEYWORDS:
                if kw in q_raw and kw in item_text:
                    # Higher bonus if the keyword is part of the primary item name rather than trailing note
                    primary_name = item_text.split("(")[0].strip()
                    if kw in primary_name:
                        raw_score = min(1.0, raw_score + 0.35)
                    else:
                        raw_score = min(1.0, raw_score + 0.20)
                    break

            # Check specification conflict and requirement
            item_specs = self.extract_specs(item_text)
            if q_specs:
                if self.has_spec_conflict(q_specs, item_specs):
                    # Penalize severely to prevent wrong specification selection
                    raw_score = raw_score * 0.2
                elif q_specs & item_specs:
                    # Boost if key specification matches
                    raw_score = min(1.0, raw_score + 0.15)

            if raw_score >= min_score:
                candidates.append({
                    "price_id": r.price_id,
                    "record": r,
                    "score": round(raw_score, 4),
                    "retrieval_method": "fuzzy",
                    "specs": list(item_specs),
                })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        logger.debug(f"FuzzyRetriever found {len(candidates)} candidates for query: '{query}'")
        return candidates
