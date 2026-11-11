"""Ingestion Service coordinating Excel Extraction, Normalization, Validation, and Storage."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import logger, settings
from app.database.sqlite_db import SQLiteDatabase
from app.database.vector_db import VectorDatabase
from app.ingestion.data_normalizer import DataNormalizer
from app.ingestion.data_validator import DataValidator, ValidationError
from app.ingestion.excel_loader import ExcelLoader
from app.schemas.price_record import ImportReport, PriceRecord


class IngestionService:
    """Orchestrates data ingestion from Excel into SQLite and Vector Database."""

    def __init__(
        self,
        sqlite_db: SQLiteDatabase | None = None,
        vector_db: VectorDatabase | None = None,
        excel_path: str | Path | None = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDatabase(settings.get_sqlite_path())
        self.vector_db = vector_db
        if self.vector_db is None and settings.enable_semantic_search:
            try:
                self.vector_db = VectorDatabase(
                    persist_directory=settings.get_faiss_dir(),
                )
            except Exception as e:
                logger.warning(f"Could not initialize FAISS VectorDatabase during ingestion: {e}")
                self.vector_db = None

        self.excel_path = Path(excel_path) if excel_path else settings.get_excel_path()

    def run_ingestion(
        self,
        excel_path: str | Path | None = None,
        clean_rebuild: bool = False,
    ) -> ImportReport:
        """Execute full ingestion pipeline.

        Args:
            excel_path: Optional override path for the Excel file.
            clean_rebuild: Whether to clear existing records before inserting.

        Returns:
            ImportReport summarizing execution metrics, issues, and counts.
        """
        if excel_path:
            self.excel_path = Path(excel_path)
            if not self.excel_path.exists():
                from app.config import PROJECT_ROOT
                alt_p = PROJECT_ROOT / self.excel_path
                if alt_p.exists():
                    self.excel_path = alt_p

        logger.info(f"Starting ingestion pipeline from {self.excel_path} (clean_rebuild={clean_rebuild})")
        loader = ExcelLoader(self.excel_path)
        sections = loader.load_raw_sections()

        source_file_hash = sections["source_file_hash"]
        worksheet_name = sections.get("worksheet_name", ExcelLoader.TARGET_WORKSHEET)
        title_text = sections["title_text"]
        header_note = sections["header_note"]

        # Parse global metadata from header
        default_date = DataNormalizer.parse_price_date(title_text)
        vat_included = False  # Header: "ไม่รวม VAT 7% และไม่รวมค่าขนส่ง"
        transportation_included = False

        validated_records: list[PriceRecord] = []
        issues: list[str] = []

        total_rows_read = sections["total_rows_read"]
        elements_raw = sections.get("elements", [])
        materials_raw = sections.get("materials", [])
        labor_raw = sections.get("labor", [])

        # 1. Process Element Items (BIM Elements & Fixtures)
        for idx, item_data in enumerate(elements_raw, start=1):
            row_idx = item_data["row_index"]
            try:
                price_id = f"ELE-{idx:03d}"
                raw_item_name = item_data["raw_item_name"]
                normalized_name = DataNormalizer.normalize_text(raw_item_name)
                raw_unit = item_data["raw_unit"]
                normalized_unit = DataNormalizer.normalize_unit(raw_unit)
                unit_price = DataNormalizer.parse_price(item_data["raw_price"])
                market_min, market_max = DataNormalizer.parse_market_range(item_data["raw_range"])
                raw_note = item_data["raw_note"]
                source_name, source_url = DataNormalizer.extract_sources_and_urls(raw_note)
                item_date = DataNormalizer.parse_price_date(raw_note, default_date=default_date)
                bim_meta = DataNormalizer.extract_bim_metadata(raw_item_name)

                record_dict = {
                    "price_id": price_id,
                    "record_type": "element",
                    "item_name": raw_item_name.strip(),
                    "normalized_item_name": normalized_name,
                    "bim_family": bim_meta["bim_family"],
                    "bim_type": bim_meta["bim_type"],
                    "category": bim_meta["bim_category"],
                    "description": None,
                    "unit": raw_unit.strip() if raw_unit else "",
                    "normalized_unit": normalized_unit,
                    "unit_price": unit_price,
                    "market_min": market_min,
                    "market_max": market_max,
                    "currency": "THB",
                    "price_date": item_date,
                    "source_name": source_name,
                    "source_url": source_url,
                    "source_note": raw_note.strip() if raw_note else None,
                    "vat_included": vat_included,
                    "transportation_included": transportation_included,
                    "original_excel_row": row_idx,
                    "raw_source_data": {
                        "row": row_idx,
                        "raw_item": raw_item_name,
                        "raw_unit": raw_unit,
                        "raw_price": item_data["raw_price"],
                        "raw_note": raw_note,
                        "raw_range": item_data["raw_range"],
                    },
                    "imported_at": datetime.now(timezone.utc),
                }

                record = DataValidator.validate_and_create_model(record_dict)
                validated_records.append(record)

            except Exception as e:
                msg = f"Row {row_idx} (Element): {e}"
                logger.error(msg)
                issues.append(msg)

        # 2. Process Material Items
        for idx, item_data in enumerate(materials_raw, start=1):
            row_idx = item_data["row_index"]
            try:
                price_id = f"MAT-{idx:03d}"
                raw_item_name = item_data["raw_item_name"]
                normalized_name = DataNormalizer.normalize_text(raw_item_name)
                raw_unit = item_data["raw_unit"]
                normalized_unit = DataNormalizer.normalize_unit(raw_unit)
                unit_price = DataNormalizer.parse_price(item_data["raw_price"])
                market_min, market_max = DataNormalizer.parse_market_range(item_data["raw_range"])
                raw_note = item_data["raw_note"]
                source_name, source_url = DataNormalizer.extract_sources_and_urls(raw_note)
                item_date = DataNormalizer.parse_price_date(raw_note, default_date=default_date)

                record_dict = {
                    "price_id": price_id,
                    "record_type": "material",
                    "item_name": raw_item_name.strip(),
                    "normalized_item_name": normalized_name,
                    "category": None,  # Not present in source Excel
                    "description": None,
                    "unit": raw_unit.strip() if raw_unit else "",
                    "normalized_unit": normalized_unit,
                    "unit_price": unit_price,
                    "market_min": market_min,
                    "market_max": market_max,
                    "currency": "THB",
                    "price_date": item_date,
                    "source_name": source_name,
                    "source_url": source_url,
                    "source_note": raw_note.strip() if raw_note else None,
                    "vat_included": vat_included,
                    "transportation_included": transportation_included,
                    "original_excel_row": row_idx,
                    "raw_source_data": {
                        "row": row_idx,
                        "raw_item": raw_item_name,
                        "raw_unit": raw_unit,
                        "raw_price": item_data["raw_price"],
                        "raw_note": raw_note,
                        "raw_range": item_data["raw_range"],
                    },
                    "imported_at": datetime.now(timezone.utc),
                }

                record = DataValidator.validate_and_create_model(record_dict)
                validated_records.append(record)

            except Exception as e:
                msg = f"Row {row_idx} (Material): {e}"
                logger.error(msg)
                issues.append(msg)

        # 3. Process Labor Items
        for idx, item_data in enumerate(labor_raw, start=1):
            row_idx = item_data["row_index"]
            try:
                price_id = f"LAB-{idx:03d}"
                raw_item_name = item_data["raw_item_name"]
                normalized_name = DataNormalizer.normalize_text(raw_item_name)
                raw_unit = item_data["raw_unit"]
                normalized_unit = DataNormalizer.normalize_unit(raw_unit)
                unit_price = DataNormalizer.parse_price(item_data["raw_price"])
                market_min, market_max = DataNormalizer.parse_market_range(item_data["raw_range"])
                raw_note = item_data["raw_note"]
                source_name, source_url = DataNormalizer.extract_sources_and_urls(raw_note)
                item_date = DataNormalizer.parse_price_date(raw_note, default_date=default_date)

                record_dict = {
                    "price_id": price_id,
                    "record_type": "labor",
                    "item_name": raw_item_name.strip(),
                    "normalized_item_name": normalized_name,
                    "category": None,
                    "description": None,
                    "unit": raw_unit.strip() if raw_unit else "",
                    "normalized_unit": normalized_unit,
                    "unit_price": unit_price,
                    "market_min": market_min,
                    "market_max": market_max,
                    "currency": "THB",
                    "price_date": item_date,
                    "source_name": source_name,
                    "source_url": source_url,
                    "source_note": raw_note.strip() if raw_note else None,
                    "vat_included": vat_included,
                    "transportation_included": transportation_included,
                    "original_excel_row": row_idx,
                    "raw_source_data": {
                        "row": row_idx,
                        "raw_item": raw_item_name,
                        "raw_unit": raw_unit,
                        "raw_price": item_data["raw_price"],
                        "raw_note": raw_note,
                        "raw_range": item_data["raw_range"],
                    },
                    "imported_at": datetime.now(timezone.utc),
                }

                record = DataValidator.validate_and_create_model(record_dict)
                validated_records.append(record)

            except Exception as e:
                msg = f"Row {row_idx} (Labor): {e}"
                logger.error(msg)
                issues.append(msg)

        # 4. Save to SQLite (Source of Truth)
        if clean_rebuild:
            self.sqlite_db.clear_all_records()
            if self.vector_db is not None:
                self.vector_db.clear()

        records_created = 0
        records_updated = 0
        ele_count = 0
        mat_count = 0
        lab_count = 0

        for r in validated_records:
            is_new = self.sqlite_db.upsert_price(r)
            if is_new:
                records_created += 1
            else:
                records_updated += 1

            if r.record_type == "element":
                ele_count += 1
            elif r.record_type == "material":
                mat_count += 1
            else:
                lab_count += 1

        # 5. Save metadata to SQLite
        self.sqlite_db.set_metadata("source_excel_file", self.excel_path.name)
        self.sqlite_db.set_metadata("source_worksheet", worksheet_name)
        self.sqlite_db.set_metadata("source_file_hash", source_file_hash)
        self.sqlite_db.set_metadata("imported_at", datetime.now(timezone.utc).isoformat())
        self.sqlite_db.set_metadata("total_element_records", str(ele_count))
        self.sqlite_db.set_metadata("total_material_records", str(mat_count))
        self.sqlite_db.set_metadata("total_labor_records", str(lab_count))
        self.sqlite_db.set_metadata("total_records", str(len(validated_records)))
        if default_date:
            self.sqlite_db.set_metadata("latest_price_date", default_date.isoformat())

        # 6. Populate Vector Database if enabled
        if self.vector_db is not None:
            try:
                self.vector_db.upsert_records(validated_records)
            except Exception as e:
                msg = f"Vector indexing error: {e}"
                logger.warning(msg)
                issues.append(msg)

        status = "success" if not issues else ("partial" if validated_records else "failed")
        rows_skipped = total_rows_read - len(validated_records)

        report = ImportReport(
            total_rows_read=total_rows_read,
            elements_imported=ele_count,
            materials_imported=mat_count,
            labor_imported=lab_count,
            records_created=records_created,
            records_updated=records_updated,
            rows_skipped=rows_skipped,
            issues_found=issues,
            source_hash=source_file_hash,
            status=status,
        )

        logger.info(
            f"Ingestion completed: {ele_count} elements, {mat_count} materials, {lab_count} labor, "
            f"{records_created} created, {records_updated} updated, status={status}"
        )
        return report
