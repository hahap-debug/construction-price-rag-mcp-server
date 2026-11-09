"""Semantic Search Retriever using ChromaDB and SQLite Source of Truth."""

from typing import Any
from app.config import logger
from app.database.sqlite_db import SQLiteDatabase
from app.database.vector_db import VectorDatabase


class SemanticRetriever:
    """Performs semantic similarity retrieval using ChromaDB embeddings."""

    def __init__(
        self,
        vector_db: VectorDatabase | None,
        sqlite_db: SQLiteDatabase,
        similarity_threshold: float = 0.30,
    ):
        self.vector_db = vector_db
        self.sqlite_db = sqlite_db
        self.threshold = similarity_threshold

    def search(
        self,
        query: str,
        record_type: str | None = None,
        unit: str | None = None,
        max_results: int = 5,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve semantically similar records from vector store, then fetch full record from SQLite.

        Returns:
            List of candidate dictionaries with price_id, record, score, and method='semantic'.
        """
        if not self.vector_db or not query.strip():
            return []

        min_score = threshold if threshold is not None else self.threshold

        try:
            vector_candidates = self.vector_db.query_semantic(
                query=query,
                n_results=max_results * 2,  # Query wider pool for post-filtering
                record_type=record_type,
                unit=unit,
            )

            candidates: list[dict[str, Any]] = []
            for vc in vector_candidates:
                score = vc["similarity_score"]
                if score < min_score:
                    continue

                pid = vc["price_id"]
                # Fetch ground truth record from SQLite
                record = self.sqlite_db.get_price_by_id(pid)
                if not record:
                    continue

                candidates.append({
                    "price_id": pid,
                    "record": record,
                    "score": score,
                    "retrieval_method": "semantic",
                    "distance": vc.get("distance"),
                })

            candidates.sort(key=lambda x: x["score"], reverse=True)
            logger.debug(f"SemanticRetriever found {len(candidates)} candidates for query: '{query}'")
            return candidates[:max_results]

        except Exception as e:
            logger.warning(f"SemanticRetriever error during query '{query}': {e}. Returning empty list.")
            return []
