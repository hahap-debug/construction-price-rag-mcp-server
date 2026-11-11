"""Service Layer coordinating MCP Tools with Retrieval and Database Layers."""

from datetime import date
from typing import Any, Literal
from app.config import logger, settings
from app.database.sqlite_db import SQLiteDatabase
from app.database.vector_db import VectorDatabase
from app.retrieval.hybrid_retriever import HybridRetriever
from app.schemas.price_record import DatabaseInfo, PriceRecordResponse, SearchResponse


class PriceService:
    """Core business logic service for construction price queries and lookups."""

    def __init__(
        self,
        sqlite_db: SQLiteDatabase | None = None,
        vector_db: VectorDatabase | None = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDatabase(settings.get_sqlite_path())
        self.vector_db = vector_db
        if self.vector_db is None and settings.enable_semantic_search:
            try:
                self.vector_db = VectorDatabase(
                    persist_directory=settings.get_faiss_dir(),
                )
            except Exception as e:
                logger.warning(f"FAISS VectorDatabase not available in PriceService: {e}")
                self.vector_db = None

        self.retriever = HybridRetriever(
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
        )

    def search_prices(
        self,
        query: str | None = None,
        material: str | None = None,
        record_type: Literal["element", "material", "labor", "all"] = "all",
        unit: str | None = None,
        as_of: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Search construction element, material, or labor prices using hybrid retrieval."""
        effective_query = (material or query or "").strip()
        if not effective_query:
            return {
                "status": "error",
                "query": query,
                "material": material,
                "total_results": 0,
                "results": [],
                "message": "Query or material parameter cannot be empty.",
            }

        valid_types = ("element", "material", "labor", "all")
        if record_type not in valid_types:
            return {
                "status": "error",
                "query": query,
                "total_results": 0,
                "results": [],
                "message": f"Invalid record_type '{record_type}'. Allowed values: {valid_types}.",
            }

        as_of_date: date | None = None
        if as_of:
            try:
                as_of_date = date.fromisoformat(as_of.strip())
            except ValueError:
                return {
                    "status": "error",
                    "query": query,
                    "total_results": 0,
                    "results": [],
                    "message": f"Invalid date format '{as_of}'. Expected ISO format 'YYYY-MM-DD'.",
                }

        effective_max = max(1, min(max_results, 50))

        response: SearchResponse = self.retriever.retrieve(
            query=effective_query,
            record_type=record_type,
            unit=unit,
            as_of=as_of_date,
            max_results=effective_max,
        )

        return response.model_dump(mode="json")

    def get_price(self, price_id: str) -> dict[str, Any]:
        """Retrieve full details of a specific price record by price_id."""
        clean_id = price_id.strip().upper() if price_id else ""
        if not clean_id:
            return {
                "status": "error",
                "price_id": price_id,
                "record": None,
                "message": "price_id is required.",
            }

        record = self.sqlite_db.get_price_by_id(clean_id)
        if not record:
            return {
                "status": "not_found",
                "price_id": clean_id,
                "record": None,
                "message": f"No price record found with ID '{clean_id}'.",
            }

        return {
            "status": "success",
            "price_id": clean_id,
            "record": record.model_dump(mode="json"),
        }

    def match_material(
        self,
        material: str,
        record_type: Literal["element", "material", "labor", "all"] = "all",
        unit: str | None = None,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> dict[str, Any]:
        """Match a BIM element, material, or labor string against FAISS Vector Database."""
        clean_mat = (material or "").strip()
        if not clean_mat:
            return {
                "status": "error",
                "material_query": material,
                "total_matches": 0,
                "matches": [],
                "message": "Parameter 'material' cannot be empty.",
            }

        if self.vector_db is None and settings.enable_semantic_search:
            try:
                self.vector_db = VectorDatabase(
                    persist_directory=settings.get_faiss_dir(),
                )
            except Exception as e:
                logger.warning(f"Could not initialize FAISS VectorDatabase: {e}")

        if self.vector_db is None:
            return {
                "status": "error",
                "material_query": clean_mat,
                "total_matches": 0,
                "matches": [],
                "message": "Vector database is not available.",
            }

        effective_top_k = max(1, min(top_k, 50))
        vector_candidates = self.vector_db.query_semantic(
            query=clean_mat,
            n_results=effective_top_k,
            record_type=record_type if record_type != "all" else None,
            unit=unit,
        )

        matches: list[dict[str, Any]] = []
        for cand in vector_candidates:
            pid = cand.get("price_id")
            score = cand.get("similarity_score", 0.0)
            if score < min_similarity:
                continue

            rec = self.sqlite_db.get_price_by_id(pid)
            if not rec:
                continue

            matches.append({
                "price_id": rec.price_id,
                "record_type": rec.record_type,
                "item_name": rec.item_name,
                "unit": rec.unit,
                "unit_price": str(rec.unit_price),
                "market_min": str(rec.market_min) if rec.market_min else None,
                "market_max": str(rec.market_max) if rec.market_max else None,
                "bim_family": getattr(rec, "bim_family", None),
                "bim_type": getattr(rec, "bim_type", None),
                "currency": rec.currency,
                "price_date": rec.price_date.isoformat() if rec.price_date else None,
                "source_name": rec.source_name,
                "source_url": rec.source_url,
                "source_note": rec.source_note,
                "vat_included": rec.vat_included,
                "transportation_included": rec.transportation_included,
                "similarity_score": score,
                "vector_distance": cand.get("distance", 0.0),
            })

        return {
            "status": "success",
            "material_query": clean_mat,
            "total_matches": len(matches),
            "matches": matches,
        }

    def get_database_info(self) -> dict[str, Any]:
        """Retrieve overview metadata, record counts, and provenance information."""
        stats = self.sqlite_db.get_database_stats()
        source_file = self.sqlite_db.get_metadata("source_excel_file") or "Real_Price_Database.xlsx"
        source_worksheet = self.sqlite_db.get_metadata("source_worksheet") or "วัสดุพื้นฐาน"
        source_file_hash = self.sqlite_db.get_metadata("source_file_hash") or "unknown"
        import_timestamp = self.sqlite_db.get_metadata("imported_at") or "unknown"
        latest_date = self.sqlite_db.get_metadata("latest_price_date") or stats.get("latest_price_date")

        info = DatabaseInfo(
            database_name="Construction Price & Labor Rates Database",
            source_excel_file=source_file,
            source_worksheet=source_worksheet,
            source_file_hash=source_file_hash,
            total_element_records=stats["total_element_records"],
            total_material_records=stats["total_material_records"],
            total_labor_records=stats["total_labor_records"],
            total_records=stats["total_records"],
            latest_price_date=latest_date,
            import_timestamp=import_timestamp,
        )
        return info.model_dump(mode="json")

    def rebuild_database(self, file_path: str | None = None) -> dict[str, Any]:
        """Rebuild SQLite and FAISS database from scratch using Excel worksheets."""
        from app.ingestion.excel_loader import ExcelLoader, ExcelLoadError
        from app.ingestion.ingestion_service import IngestionService

        input_path = file_path or str(settings.get_excel_path())

        try:
            resolved_file = ExcelLoader.resolve_excel_path(input_path)
            ExcelLoader.validate_excel_file(resolved_file)
        except ExcelLoadError as err:
            return {
                "status": "error",
                "message": str(err),
                "file_path": str(file_path),
            }

        try:
            ingestion_svc = IngestionService(
                sqlite_db=self.sqlite_db,
                vector_db=self.vector_db,
                excel_path=resolved_file,
            )
            report = ingestion_svc.run_ingestion(clean_rebuild=True)
        except ExcelLoadError as err:
            return {
                "status": "error",
                "message": str(err),
                "file_path": str(resolved_file),
            }
        except Exception as e:
            logger.error(f"Rebuild database unexpected error: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"เกิดข้อผิดพลาดระหว่างนำเข้าข้อมูล: {e}",
                "file_path": str(resolved_file),
            }

        stats = self.sqlite_db.get_database_stats()
        vector_count = self.vector_db.count() if self.vector_db else 0

        return {
            "status": "success" if report.status in ("success", "partial") else "failed",
            "file_name": resolved_file.name,
            "file_path": str(resolved_file),
            "worksheet_used": self.sqlite_db.get_metadata("source_worksheet"),
            "elements_imported": report.elements_imported,
            "materials_imported": report.materials_imported,
            "labor_imported": report.labor_imported,
            "total_records": stats["total_records"],
            "vector_index_size": vector_count,
            "issues": report.issues_found,
            "message": (
                f"สร้างฐานข้อมูลราคาใหม่เรียบร้อยแล้ว: ชิ้นส่วน BIM (Element) {report.elements_imported} รายการ, "
                f"วัสดุก่อสร้าง (Material) {report.materials_imported} รายการ, "
                f"ค่าแรงงาน (Labor) {report.labor_imported} รายการ (รวม {stats['total_records']} รายการ) "
                f"และอัปเดต FAISS Vector Index เรียบร้อย พร้อมค้นหาด้วย match_material ทันที"
            ),
        }
