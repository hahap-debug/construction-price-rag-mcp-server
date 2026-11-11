"""FAISS Vector Database Layer for Construction Price Semantic Indexing."""

from pathlib import Path
from typing import Any
import json
import numpy as np

from app.config import logger
from app.embeddings.embedding_provider import BaseEmbeddingProvider, get_embedding_provider
from app.schemas.price_record import PriceRecord


class VectorDatabase:
    """Manages vector embeddings using FAISS (IndexFlatIP) for ultra-fast semantic retrieval.
    
    FAISS runs entirely in-memory with disk persistence, eliminating heavy client/telemetry overhead.
    All definitive pricing data must be fetched from SQLite using the returned price_id.
    """

    def __init__(
        self,
        persist_directory: str | Path | None = None,
        collection_name: str = "construction_prices",
        embedding_provider: BaseEmbeddingProvider | None = None,
    ):
        import faiss

        if persist_directory is None:
            from app.config import settings
            self.persist_directory = settings.get_faiss_dir()
        else:
            p = Path(persist_directory)
            if p.is_absolute():
                self.persist_directory = p
            else:
                from app.config import PROJECT_ROOT, settings
                if (PROJECT_ROOT / p).exists():
                    self.persist_directory = PROJECT_ROOT / p
                elif settings.get_faiss_dir().exists() and p.name == "faiss_index":
                    self.persist_directory = settings.get_faiss_dir()
                else:
                    self.persist_directory = PROJECT_ROOT / p

        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.dim = getattr(self.embedding_provider, "dim", 384)

        self.index_path = self.persist_directory / "index.faiss"
        self.meta_path = self.persist_directory / "metadata.json"

        self.index: Any = faiss.IndexFlatIP(self.dim)
        self.metadata: list[dict[str, Any]] = []

        self._load_from_disk()
        logger.info(
            f"Initialized FAISS VectorDatabase at {self.persist_directory} "
            f"(items: {self.count()}, dim: {self.dim})"
        )

    def _load_from_disk(self) -> None:
        """Load FAISS index and metadata from disk if available."""
        import faiss

        if self.index_path.exists() and self.meta_path.exists():
            try:
                self.index = faiss.read_index(str(self.index_path))
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                logger.info(f"Loaded {self.count()} FAISS vectors from {self.index_path}")
            except Exception as e:
                logger.warning(f"Could not load existing FAISS index: {e}. Reinitializing empty index.")
                self.index = faiss.IndexFlatIP(self.dim)
                self.metadata = []

    def _save_to_disk(self) -> None:
        """Persist FAISS index and metadata to disk."""
        import faiss

        try:
            faiss.write_index(self.index, str(self.index_path))
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {self.count()} FAISS vectors to {self.index_path}")
        except Exception as e:
            logger.error(f"Failed to persist FAISS index: {e}", exc_info=True)
            raise

    def clear(self) -> None:
        """Clear FAISS index and metadata for a fresh rebuild, removing old disk files first."""
        import faiss
        self.index = faiss.IndexFlatIP(self.dim)
        self.metadata = []
        if self.index_path.exists():
            try:
                self.index_path.unlink()
            except Exception as e:
                logger.warning(f"Could not unlink old index file {self.index_path}: {e}")
        if self.meta_path.exists():
            try:
                self.meta_path.unlink()
            except Exception as e:
                logger.warning(f"Could not unlink old metadata file {self.meta_path}: {e}")
        self._save_to_disk()
        logger.info(f"Cleared FAISS VectorDatabase at {self.persist_directory}")

    def _prepare_document_text(self, record: PriceRecord) -> str:
        """Create rich descriptive text for semantic indexing based strictly on factual source data."""
        if record.record_type == "element":
            type_str = "องค์ประกอบอาคาร (Element)"
        elif record.record_type == "material":
            type_str = "วัสดุก่อสร้าง (Material)"
        else:
            type_str = "ค่าแรงงาน (Labor)"

        parts = [f"ประเภท: {type_str}"]
        if record.category:
            parts.append(f"หมวดงาน: {record.category}")
        if getattr(record, "bim_family", None):
            parts.append(f"BIM Family: {record.bim_family}")
        if getattr(record, "bim_type", None):
            parts.append(f"BIM Type: {record.bim_type}")
        parts.append(f"รายการ: {record.item_name}")
        if record.unit:
            parts.append(f"หน่วย: {record.unit}")
        if record.source_note:
            parts.append(f"ที่มา: {record.source_note}")
        return " | ".join(parts)

    def upsert_records(self, records: list[PriceRecord]) -> int:
        """Embed and upsert price records into the FAISS index with idempotency."""
        if not records:
            return 0
        import faiss

        # Existing metadata indexed by price_id for idempotent updating
        existing_map: dict[str, dict[str, Any]] = {
            m["price_id"]: m for m in self.metadata
        }

        # Update or add new records
        for r in records:
            doc_text = self._prepare_document_text(r)
            existing_map[r.price_id] = {
                "price_id": r.price_id,
                "record_type": r.record_type,
                "item_name": r.item_name,
                "unit": r.unit,
                "normalized_unit": r.normalized_unit,
                "bim_family": getattr(r, "bim_family", None),
                "bim_type": getattr(r, "bim_type", None),
                "original_excel_row": r.original_excel_row,
                "document": doc_text,
            }

        all_items = list(existing_map.values())
        documents = [item["document"] for item in all_items]

        # Generate embeddings
        raw_embeddings = self.embedding_provider.embed_documents(documents)
        embeddings = np.ascontiguousarray(raw_embeddings, dtype=np.float32)

        # Build fresh FAISS IndexFlatIP (Inner Product on L2-normalized vectors = Cosine Similarity)
        faiss.normalize_L2(embeddings)
        new_index = faiss.IndexFlatIP(self.dim)
        new_index.add(embeddings)

        self.index = new_index
        self.metadata = all_items

        self._save_to_disk()
        return len(records)

    def query_semantic(
        self,
        query: str,
        n_results: int = 5,
        record_type: str | None = None,
        unit: str | None = None,
    ) -> list[dict[str, Any]]:
        """Perform semantic search against FAISS and return matching candidate IDs with scores."""
        clean_q = query.strip() if query else ""
        if not clean_q or self.count() == 0:
            return []
        import faiss

        try:
            raw_query_emb = self.embedding_provider.embed_query(clean_q)
            q_emb = np.ascontiguousarray([raw_query_emb], dtype=np.float32)
            faiss.normalize_L2(q_emb)

            # Retrieve top candidates (search full index when post-filtering by record_type or unit)
            if (record_type and record_type != "all") or unit:
                k_search = self.count()
            else:
                k_search = min(max(n_results * 10, 50), self.count())
            distances, indices = self.index.search(q_emb, k_search)

            candidates: list[dict[str, Any]] = []
            for score, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self.metadata):
                    continue

                meta = self.metadata[idx]

                # Metadata filtering
                if record_type and record_type != "all" and meta.get("record_type") != record_type:
                    continue
                if unit:
                    from app.ingestion.data_normalizer import DataNormalizer
                    norm_q_unit = DataNormalizer.resolve_query_unit(unit)
                    m_norm = DataNormalizer.resolve_query_unit(meta.get("normalized_unit") or meta.get("unit"))
                    if norm_q_unit != m_norm and meta.get("normalized_unit") != unit and meta.get("unit") != unit:
                        continue

                sim_score = max(0.0, min(1.0, float(score)))
                candidates.append({
                    "price_id": meta["price_id"],
                    "distance": round(float(1.0 - sim_score), 4),
                    "similarity_score": round(sim_score, 4),
                    "document": meta.get("document", ""),
                    "retrieval_method": "semantic",
                })

                if len(candidates) >= n_results:
                    break

            return candidates
        except Exception as e:
            logger.warning(f"FAISS semantic search failed: {e}. Falling back gracefully.")
            return []

    def count(self) -> int:
        """Return the number of vectors stored in the index."""
        return self.index.ntotal if self.index is not None else 0

    def clear(self) -> None:
        """Clear all records in the index and delete storage files."""
        import faiss

        self.index = faiss.IndexFlatIP(self.dim)
        self.metadata = []
        if self.index_path.exists():
            self.index_path.unlink()
        if self.meta_path.exists():
            self.meta_path.unlink()
        logger.info(f"Cleared FAISS VectorDatabase at {self.persist_directory}")


# Class alias for explicit FAISS naming
FaissDatabase = VectorDatabase
