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
        """Match a BIM element, material, or labor string using hybrid retrieval."""
        clean_mat = (material or "").strip()
        if not clean_mat:
            return {
                "status": "error",
                "material_query": material,
                "total_matches": 0,
                "matches": [],
                "message": "Parameter 'material' cannot be empty.",
            }

        effective_top_k = max(1, min(top_k, 50))
        response = self.retriever.retrieve(
            query=clean_mat,
            record_type=record_type,
            unit=unit,
            max_results=effective_top_k,
        )

        matches: list[dict[str, Any]] = []
        for result in response.results:
            score = result.confidence_score
            if score < min_similarity:
                continue
            source_record = self.sqlite_db.get_price_by_id(result.price_id)

            matches.append({
                "price_id": result.price_id,
                "record_type": result.record_type,
                "item_name": result.item_name,
                "unit": result.unit,
                "raw_unit": source_record.unit if source_record else result.unit,
                "unit_price": str(result.unit_price),
                "market_min": str(result.market_min) if result.market_min is not None else None,
                "market_max": str(result.market_max) if result.market_max is not None else None,
                "bim_family": result.bim_family,
                "bim_type": result.bim_type,
                "currency": result.currency,
                "price_date": result.price_date,
                "source_name": result.source_name,
                "source_url": result.source_url,
                "source_note": result.source_note,
                "vat_included": result.vat_included,
                "transportation_included": result.transportation_included,
                "similarity_score": score,
                "vector_distance": None,
                "retrieval_method": result.retrieval_method,
            })

        return {
            "status": "success",
            "material_query": clean_mat,
            "total_matches": len(matches),
            "matches": matches,
        }

    def match_composite_rate(
        self,
        query: str,
        unit: str | None = None,
        standard_label: str | None = None,
        boq_category: str | None = None,
        min_similarity: float = 0.0,
    ) -> dict[str, Any]:
        """Dynamically assemble a composite rate (Material Rate + Labor Rate) for a BIM query on-the-fly."""
        clean_q = (query or "").strip()
        if not clean_q:
            return {"status": "error", "message": "query cannot be empty"}

        if self.vector_db is None and settings.enable_semantic_search:
            try:
                self.vector_db = VectorDatabase(persist_directory=settings.get_faiss_dir())
            except Exception as e:
                logger.warning(f"VectorDatabase init error: {e}")

        if not self.vector_db:
            return {"status": "error", "message": "Vector database not available"}

        from decimal import Decimal
        from app.schemas.cost_record import CostRecord

        # Search material candidates
        mat_cands = self.vector_db.query_semantic(clean_q, n_results=3, record_type="material", unit=unit)
        best_mat = mat_cands[0] if mat_cands else None
        mat_rec = self.sqlite_db.get_price_by_id(best_mat["price_id"]) if best_mat else None

        # Search labor candidates
        lab_cands = self.vector_db.query_semantic(clean_q, n_results=3, record_type="labor", unit=unit)
        best_lab = lab_cands[0] if lab_cands else None
        lab_rec = self.sqlite_db.get_price_by_id(best_lab["price_id"]) if best_lab else None

        # Also search element benchmark
        ele_cands = self.vector_db.query_semantic(clean_q, n_results=1, record_type="element", unit=unit)
        best_ele = ele_cands[0] if ele_cands else None
        ele_rec = self.sqlite_db.get_price_by_id(best_ele["price_id"]) if best_ele else None

        mat_rate = mat_rec.unit_price if mat_rec else Decimal("0")
        lab_rate = lab_rec.unit_price if lab_rec else Decimal("0")
        unit_rate = mat_rate + lab_rate

        # If material and labor are both missing, but element benchmark exists, use element benchmark
        if unit_rate == 0 and ele_rec:
            unit_rate = ele_rec.unit_price
            mat_rate = ele_rec.unit_price

        # Compute dynamic confidence score
        scores = []
        if best_mat:
            scores.append(best_mat["similarity_score"])
        if best_lab:
            scores.append(best_lab["similarity_score"])
        if not scores and best_ele:
            scores.append(best_ele["similarity_score"])

        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0
        status = "matched" if avg_score >= 0.70 and unit_rate > 0 else "requires_review"

        resolved_unit = unit or (mat_rec.normalized_unit if mat_rec else (lab_rec.normalized_unit if lab_rec else "หน่วย"))
        cost_code = f"CST-{mat_rec.price_id if mat_rec else 'GEN'}-{lab_rec.price_id if lab_rec else 'GEN'}"
        category = boq_category or (ele_rec.category if ele_rec else (mat_rec.category if mat_rec else "03-CONCRETE"))
        description = f"{clean_q} (ประกอบราคา: {mat_rec.item_name if mat_rec else 'วัสดุทั่วไป'} + {lab_rec.item_name if lab_rec else 'ค่าแรงทั่วไป'})"

        cost_rec = CostRecord(
            cost_code=cost_code,
            description=description,
            boq_category=category,
            unit=resolved_unit,
            standard_labels=[standard_label] if standard_label else [],
            material_rate=mat_rate,
            labor_rate=lab_rate,
            equipment_rate=Decimal("0"),
            unit_rate=unit_rate,
            source=f"{mat_rec.source_name if mat_rec else ''} + {lab_rec.source_name if lab_rec else ''}".strip(" +") or "Real_Price_Database",
            price_date=(mat_rec.price_date or lab_rec.price_date or date.today()).isoformat(),
            approved=False,
            database_version="2026.11",
        )

        return {
            "status": status,
            "query": clean_q,
            "confidence_score": avg_score,
            "cost_record": cost_rec.model_dump(mode="json"),
            "material_match": {
                "price_id": mat_rec.price_id,
                "item_name": mat_rec.item_name,
                "rate": str(mat_rate),
                "similarity": best_mat["similarity_score"] if best_mat else 0.0,
            } if mat_rec else None,
            "labor_match": {
                "price_id": lab_rec.price_id,
                "item_name": lab_rec.item_name,
                "rate": str(lab_rate),
                "similarity": best_lab["similarity_score"] if best_lab else 0.0,
            } if lab_rec else None,
        }

    def batch_match_prices(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Process batch price requests dynamically using vectorized batch search."""
        if not items:
            return {
                "status": "success",
                "total_queries": 0,
                "matched_count": 0,
                "review_count": 0,
                "no_match_count": 0,
                "items": [],
            }

        if self.vector_db is None and settings.enable_semantic_search:
            try:
                self.vector_db = VectorDatabase(persist_directory=settings.get_faiss_dir())
            except Exception as e:
                logger.warning(f"VectorDatabase init error: {e}")

        queries = [item.get("query", "").strip() for item in items]
        units = [item.get("unit") for item in items]

        # Dynamic batch search for materials and labor
        mat_batch = self.vector_db.query_semantic_batch(queries, n_results=1, record_type="material", units=units) if self.vector_db else [[] for _ in queries]
        lab_batch = self.vector_db.query_semantic_batch(queries, n_results=1, record_type="labor", units=units) if self.vector_db else [[] for _ in queries]
        ele_batch = self.vector_db.query_semantic_batch(queries, n_results=1, record_type="element", units=units) if self.vector_db else [[] for _ in queries]

        results = []
        matched_cnt = 0
        review_cnt = 0
        no_match_cnt = 0

        from decimal import Decimal
        from app.schemas.cost_record import CostRecord, BatchMatchResultItem, BatchMatchResponse

        for idx, (raw_item, q_text) in enumerate(zip(items, queries)):
            item_id = raw_item.get("id") or raw_item.get("item_id") or f"ITEM-{idx+1:03d}"
            target_unit = raw_item.get("unit")

            best_mat = mat_batch[idx][0] if mat_batch[idx] else None
            best_lab = lab_batch[idx][0] if lab_batch[idx] else None
            best_ele = ele_batch[idx][0] if ele_batch[idx] else None

            mat_rec = self.sqlite_db.get_price_by_id(best_mat["price_id"]) if best_mat else None
            lab_rec = self.sqlite_db.get_price_by_id(best_lab["price_id"]) if best_lab else None
            ele_rec = self.sqlite_db.get_price_by_id(best_ele["price_id"]) if best_ele else None

            mat_rate = mat_rec.unit_price if mat_rec else Decimal("0")
            lab_rate = lab_rec.unit_price if lab_rec else Decimal("0")
            unit_rate = mat_rate + lab_rate
            if unit_rate == 0 and ele_rec:
                unit_rate = ele_rec.unit_price
                mat_rate = ele_rec.unit_price

            scores = []
            if best_mat:
                scores.append(best_mat["similarity_score"])
            if best_lab:
                scores.append(best_lab["similarity_score"])
            if not scores and best_ele:
                scores.append(best_ele["similarity_score"])

            avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

            if unit_rate == 0:
                item_status = "no_match"
                no_match_cnt += 1
            elif avg_score >= 0.70:
                item_status = "matched"
                matched_cnt += 1
            else:
                item_status = "requires_review"
                review_cnt += 1

            resolved_unit = target_unit or (mat_rec.normalized_unit if mat_rec else (lab_rec.normalized_unit if lab_rec else "หน่วย"))
            cost_code = f"CST-{mat_rec.price_id if mat_rec else 'GEN'}-{lab_rec.price_id if lab_rec else 'GEN'}"
            category = raw_item.get("boq_category") or (ele_rec.category if ele_rec else "03-CONCRETE")
            std_label = raw_item.get("standard_label")

            cost_rec = CostRecord(
                cost_code=cost_code,
                description=f"{q_text} ({mat_rec.item_name if mat_rec else ''} + {lab_rec.item_name if lab_rec else ''})".strip(),
                boq_category=category,
                unit=resolved_unit,
                standard_labels=[std_label] if std_label else [],
                material_rate=mat_rate,
                labor_rate=lab_rate,
                equipment_rate=Decimal("0"),
                unit_rate=unit_rate,
                source=f"{mat_rec.source_name if mat_rec else ''} + {lab_rec.source_name if lab_rec else ''}".strip(" +") or "Real_Price_Database",
                price_date=(mat_rec.price_date or lab_rec.price_date or date.today()).isoformat(),
                approved=False,
                database_version="2026.11",
            ) if unit_rate > 0 else None

            res_item = BatchMatchResultItem(
                item_id=str(item_id),
                query=q_text,
                status=item_status,
                confidence_score=avg_score,
                cost_record=cost_rec,
                material_match={
                    "price_id": mat_rec.price_id,
                    "item_name": mat_rec.item_name,
                    "rate": str(mat_rate),
                    "similarity": best_mat["similarity_score"] if best_mat else 0.0,
                } if mat_rec else None,
                labor_match={
                    "price_id": lab_rec.price_id,
                    "item_name": lab_rec.item_name,
                    "rate": str(lab_rate),
                    "similarity": best_lab["similarity_score"] if best_lab else 0.0,
                } if lab_rec else None,
            )
            results.append(res_item)

        response = BatchMatchResponse(
            status="success" if matched_cnt > 0 else ("partial" if review_cnt > 0 else "error"),
            total_queries=len(items),
            matched_count=matched_cnt,
            review_count=review_cnt,
            no_match_count=no_match_cnt,
            items=results,
        )
        return response.model_dump(mode="json")

    def export_boq_cost_records(
        self,
        standard_labels: list[str] | None = None,
        approved_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Export cost records conforming strictly to Rule-BOQ's CostRecord schema."""
        all_prices = self.sqlite_db.get_all_prices()
        from decimal import Decimal
        from app.schemas.cost_record import CostRecord

        records: list[dict[str, Any]] = []
        for p in all_prices:
            mat_rate = p.unit_price if p.record_type in ("material", "element") else Decimal("0")
            lab_rate = p.unit_price if p.record_type == "labor" else Decimal("0")
            category = p.category or ("03-CONCRETE" if "คอนกรีต" in p.item_name else "03-REINFORCEMENT")

            rec = CostRecord(
                cost_code=f"CST-{p.price_id}",
                description=p.item_name,
                boq_category=category,
                unit=p.normalized_unit or p.unit,
                standard_labels=standard_labels or [],
                material_rate=mat_rate,
                labor_rate=lab_rate,
                equipment_rate=Decimal("0"),
                unit_rate=mat_rate + lab_rate,
                source=p.source_name or "Real_Price_Database",
                price_date=p.price_date.isoformat() if p.price_date else "2026-07-01",
                approved=False,
                database_version="2026.11",
            )
            records.append(rec.model_dump(mode="json"))
            if len(records) >= limit:
                break

        return records

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
