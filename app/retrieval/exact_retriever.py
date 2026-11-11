"""Exact Search Retriever for Construction Price Records."""

import re
from typing import Any
from app.config import logger
from app.schemas.price_record import PriceRecord


class ExactRetriever:
    """Performs exact text and normalized specification matching."""

    # Thai question words and conversational filler terms to strip when extracting query core
    FILLER_WORDS = [
        r"ราคาเท่าไร", r"ราคาเท่าไหร่", r"ราคา", r"เท่าไร", r"เท่าไหร่",
        r"ขอราคา", r"ขอทราบราคา", r"กี่บาท", r"บาท", r"ขอ", r"ต้องการ",
        r"ช่วยหา", r"ค้นหา", r"หารายการ", r"รายการ", r"ต่อหน่วย",
    ]

    @classmethod
    def clean_query(cls, query: str) -> str:
        """Strip conversational filler words while strictly preserving material specifications."""
        q = query.strip()
        # Case insensitive regex for filler words
        for pattern in cls.FILLER_WORDS:
            q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
        # Collapse spaces
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def search(
        self,
        query: str,
        records: list[PriceRecord],
        record_type: str | None = None,
        unit: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for exact or normalized exact matches among candidate records.

        Returns:
            List of candidate dictionaries with price_id, score=1.0, and method='exact'.
        """
        raw_q = query.strip().lower()
        clean_q = self.clean_query(query).lower()

        if not raw_q and not clean_q:
            return []

        candidates: list[dict[str, Any]] = []

        for r in records:
            # Filter checks
            if record_type and record_type != "all" and r.record_type != record_type:
                continue
            if unit and r.normalized_unit != unit and r.unit != unit:
                continue

            item_lower = r.item_name.lower().strip()
            norm_lower = r.normalized_item_name.lower().strip()

            # 1. Direct identical match
            if raw_q == item_lower or raw_q == norm_lower:
                candidates.append({
                    "price_id": r.price_id,
                    "record": r,
                    "score": 1.0,
                    "retrieval_method": "exact",
                    "match_type": "identical",
                })
                continue

            # 2. Match with cleaned query (stripped of conversational filler words)
            if clean_q and (clean_q == item_lower or clean_q == norm_lower):
                candidates.append({
                    "price_id": r.price_id,
                    "record": r,
                    "score": 0.99,
                    "retrieval_method": "exact",
                    "match_type": "cleaned_exact",
                })
                continue

            # 3. Match Thai part or English part before/after slash
            if "/" in item_lower:
                slash_parts = [p.strip() for p in item_lower.split("/")]
                if clean_q in slash_parts or raw_q in slash_parts:
                    candidates.append({
                        "price_id": r.price_id,
                        "record": r,
                        "score": 0.99,
                        "retrieval_method": "exact",
                        "match_type": "bilingual_exact",
                    })
                    continue

            # 4. Clean query matches core item prefix before parentheses
            base_name = re.sub(r"\(.*?\)", "", item_lower).strip()
            if "/" in base_name:
                base_name_thai = re.sub(r"\(.*?\)", "", item_lower.split("/")[0]).strip()
                if clean_q and (clean_q == base_name or clean_q == base_name_thai):
                    candidates.append({
                        "price_id": r.price_id,
                        "record": r,
                        "score": 0.98,
                        "retrieval_method": "exact",
                        "match_type": "core_spec_exact",
                    })
                    continue
            elif clean_q and clean_q == base_name:
                candidates.append({
                    "price_id": r.price_id,
                    "record": r,
                    "score": 0.98,
                    "retrieval_method": "exact",
                    "match_type": "core_spec_exact",
                })
                continue

        logger.debug(f"ExactRetriever found {len(candidates)} candidates for query: '{query}'")
        return candidates
