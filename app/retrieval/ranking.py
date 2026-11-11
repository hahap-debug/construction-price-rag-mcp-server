"""Ranking and Candidate Fusion Layer implementing Reciprocal Rank Fusion (RRF)."""

from datetime import date
from typing import Any
from app.config import logger
from app.schemas.price_record import PriceRecord, SearchResultItem


class CandidateRanker:
    """Combines, deduplicates, and ranks candidates from Exact, Fuzzy, and Semantic retrievers."""

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k

    def fuse_and_rank(
        self,
        exact_candidates: list[dict[str, Any]],
        fuzzy_candidates: list[dict[str, Any]],
        semantic_candidates: list[dict[str, Any]],
        max_results: int = 5,
        as_of: date | None = None,
        q_specs: set[str] | None = None,
    ) -> list[SearchResultItem]:
        """Merge candidates across retrieval methods using priority ranking and RRF.

        Exact matches are prioritized first. Fuzzy and Semantic candidates are fused via RRF.
        """
        results: list[SearchResultItem] = []
        seen_ids: set[str] = set()

        # 1. Process Exact Matches first (Highest Priority)
        for cand in exact_candidates:
            pid = cand["price_id"]
            rec: PriceRecord = cand["record"]

            # Filter by date if as_of specified
            if as_of and rec.price_date and rec.price_date > as_of:
                continue

            if pid not in seen_ids:
                seen_ids.add(pid)
                results.append(SearchResultItem(
                    price_id=rec.price_id,
                    record_type=rec.record_type,
                    item_name=rec.item_name,
                    unit=rec.unit,
                    unit_price=rec.unit_price,
                    market_min=rec.market_min,
                    market_max=rec.market_max,
                    bim_family=getattr(rec, "bim_family", None),
                    bim_type=getattr(rec, "bim_type", None),
                    currency=rec.currency,
                    price_date=rec.price_date.isoformat() if rec.price_date else None,
                    source_name=rec.source_name,
                    source_url=rec.source_url,
                    source_note=rec.source_note,
                    vat_included=rec.vat_included,
                    transportation_included=rec.transportation_included,
                    retrieval_method=cand.get("retrieval_method", "exact"),
                    confidence_score=round(cand.get("score", 1.0), 4),
                ))

        if len(results) >= max_results:
            return results[:max_results]

        # 2. Reciprocal Rank Fusion for Fuzzy and Semantic Candidates
        # Map price_id -> {record, rrf_score, methods, sim_scores}
        fusion_map: dict[str, dict[str, Any]] = {}

        # Process Fuzzy Ranks
        for rank, cand in enumerate(fuzzy_candidates, start=1):
            pid = cand["price_id"]
            if pid in seen_ids:
                continue
            rec: PriceRecord = cand["record"]
            if as_of and rec.price_date and rec.price_date > as_of:
                continue

            rrf_val = 1.0 / (self.rrf_k + rank)
            if pid not in fusion_map:
                fusion_map[pid] = {
                    "record": rec,
                    "rrf_score": 0.0,
                    "methods": set(),
                    "sim_scores": [],
                }
            fusion_map[pid]["rrf_score"] += rrf_val
            fusion_map[pid]["methods"].add("fuzzy")
            fusion_map[pid]["sim_scores"].append(cand["score"])

        # Process Semantic Ranks
        for rank, cand in enumerate(semantic_candidates, start=1):
            pid = cand["price_id"]
            if pid in seen_ids:
                continue
            rec: PriceRecord = cand["record"]
            if as_of and rec.price_date and rec.price_date > as_of:
                continue

            rrf_val = 0.8 / (self.rrf_k + rank)
            if pid not in fusion_map:
                fusion_map[pid] = {
                    "record": rec,
                    "rrf_score": 0.0,
                    "methods": set(),
                    "sim_scores": [],
                }
            fusion_map[pid]["rrf_score"] += rrf_val
            fusion_map[pid]["methods"].add("semantic")
            fusion_map[pid]["sim_scores"].append(cand["score"])

        # Sort fused candidates by a combination of similarity score and RRF score
        # max_sim provides semantic/fuzzy fidelity, while RRF incorporates rank position
        sorted_fused = sorted(
            fusion_map.items(),
            key=lambda x: (
                0.80 * max(x[1]["sim_scores"]) + 0.20 * (x[1]["rrf_score"] * 20.0)
            ),
            reverse=True,
        )

        for pid, data in sorted_fused:
            if len(results) >= max_results:
                break
            rec: PriceRecord = data["record"]

            # If user specified technical specs (e.g. DB12), candidate must not conflict
            if q_specs:
                from app.retrieval.fuzzy_retriever import FuzzyRetriever
                item_specs = FuzzyRetriever.extract_specs(rec.item_name)
                retriever_inst = FuzzyRetriever()
                if retriever_inst.has_spec_conflict(q_specs, item_specs):
                    continue

            methods = sorted(list(data["methods"]))
            method_str = "hybrid" if len(methods) > 1 else methods[0]
            confidence = max(data["sim_scores"])

            results.append(SearchResultItem(
                price_id=rec.price_id,
                record_type=rec.record_type,
                item_name=rec.item_name,
                unit=rec.unit,
                unit_price=rec.unit_price,
                market_min=rec.market_min,
                market_max=rec.market_max,
                bim_family=getattr(rec, "bim_family", None),
                bim_type=getattr(rec, "bim_type", None),
                currency=rec.currency,
                price_date=rec.price_date.isoformat() if rec.price_date else None,
                source_name=rec.source_name,
                source_url=rec.source_url,
                source_note=rec.source_note,
                vat_included=rec.vat_included,
                transportation_included=rec.transportation_included,
                retrieval_method=method_str,
                confidence_score=round(confidence, 4),
            ))

        return results[:max_results]
