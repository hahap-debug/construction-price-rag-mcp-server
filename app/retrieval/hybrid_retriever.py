"""Hybrid Retrieval Engine combining Exact, Fuzzy, and Semantic search methods."""

from datetime import date
from typing import Literal

from app.config import logger, settings
from app.database.sqlite_db import SQLiteDatabase
from app.database.vector_db import VectorDatabase
from app.ingestion.data_normalizer import DataNormalizer
from app.retrieval.exact_retriever import ExactRetriever
from app.retrieval.fuzzy_retriever import FuzzyRetriever
from app.retrieval.ranking import CandidateRanker
from app.retrieval.semantic_retriever import SemanticRetriever
from app.schemas.price_record import SearchResponse, SearchResultItem


class HybridRetriever:
    """Coordinates Exact, Fuzzy, and Semantic retrieval pipelines."""

    def __init__(
        self,
        sqlite_db: SQLiteDatabase,
        vector_db: VectorDatabase | None = None,
        similarity_threshold: float | None = None,
        rrf_k: int | None = None,
    ):
        self.sqlite_db = sqlite_db
        self.vector_db = vector_db
        threshold = similarity_threshold or settings.default_similarity_threshold
        k = rrf_k or settings.rrf_k

        self.exact_retriever = ExactRetriever()
        self.fuzzy_retriever = FuzzyRetriever(similarity_threshold=threshold)
        self.semantic_retriever = SemanticRetriever(
            vector_db=vector_db,
            sqlite_db=sqlite_db,
            similarity_threshold=threshold,
        )
        self.ranker = CandidateRanker(rrf_k=k)

    def retrieve(
        self,
        query: str,
        record_type: Literal["material", "labor", "all"] = "material",
        unit: str | None = None,
        as_of: date | None = None,
        max_results: int = 5,
    ) -> SearchResponse:
        """Execute hybrid search pipeline with filtering, normalization, and ranking.

        Args:
            query: User search text (e.g., 'เหล็ก DB12 ราคาเท่าไร')
            record_type: Filter by 'material', 'labor', or 'all' (default: 'material')
            unit: Optional measurement unit filter (e.g. 'กก.', 'ตร.ม.', 'ถุง')
            as_of: Optional effective date filter (prices <= as_of)
            max_results: Maximum number of results to return (default: 5)

        Returns:
            Structured SearchResponse with ranked results.
        """
        clean_q = query.strip()
        if not clean_q:
            return SearchResponse(
                status="error",
                query=query,
                total_results=0,
                results=[],
                message="Search query cannot be empty",
            )

        # Normalize query unit if provided
        normalized_filter_unit = DataNormalizer.resolve_query_unit(unit) if unit else None

        # Fetch candidate pool from SQLite based on record_type
        all_records = self.sqlite_db.get_all_prices(record_type=record_type)
        if not all_records:
            return SearchResponse(
                status="no_results",
                query=query,
                total_results=0,
                results=[],
                message=f"No price records found for record_type='{record_type}' in database.",
            )

        # 1. Exact Search
        exact_matches = self.exact_retriever.search(
            query=clean_q,
            records=all_records,
            record_type=record_type,
            unit=normalized_filter_unit,
        )

        fuzzy_matches: list = []
        semantic_matches: list = []

        # If exact search didn't saturate max_results, run fuzzy and semantic
        if len(exact_matches) < max_results:
            # 2. Fuzzy Search
            fuzzy_matches = self.fuzzy_retriever.search(
                query=clean_q,
                records=all_records,
                record_type=record_type,
                unit=normalized_filter_unit,
            )

            # 3. Semantic Search (if VectorDB enabled)
            if self.vector_db is not None and settings.enable_semantic_search:
                semantic_matches = self.semantic_retriever.search(
                    query=clean_q,
                    record_type=record_type,
                    unit=normalized_filter_unit,
                    max_results=max_results,
                )

        # 4. Merge, deduplicate, and rank
        q_specs = self.fuzzy_retriever.extract_specs(clean_q)
        ranked_results: list[SearchResultItem] = self.ranker.fuse_and_rank(
            exact_candidates=exact_matches,
            fuzzy_candidates=fuzzy_matches,
            semantic_candidates=semantic_matches,
            max_results=max_results,
            as_of=as_of,
            q_specs=q_specs,
        )

        if not ranked_results:
            msg = f"No matching price records found for query '{query}'"
            if normalized_filter_unit:
                msg += f" with unit='{unit}'"
            if as_of:
                msg += f" as of date '{as_of}'"
            return SearchResponse(
                status="no_results",
                query=query,
                total_results=0,
                results=[],
                message=msg,
            )

        return SearchResponse(
            status="success",
            query=query,
            total_results=len(ranked_results),
            results=ranked_results,
        )
