"""Unit tests for Excel Data Ingestion Pipeline."""

from pathlib import Path
import pytest
from app.config import settings
from app.database.sqlite_db import SQLiteDatabase
from app.ingestion.excel_loader import ExcelLoader, ExcelLoadError
from app.ingestion.ingestion_service import IngestionService


def test_excel_loader_reads_designated_sheet():
    """Verify loader reads first worksheet 'วัสดุพื้นฐาน' and extracts row counts."""
    excel_path = settings.get_excel_path()
    loader = ExcelLoader(excel_path)
    sections = loader.load_raw_sections()

    assert sections["worksheet_name"] == "วัสดุพื้นฐาน"
    assert len(sections["materials"]) >= 20
    assert len(sections["labor"]) >= 5
    assert sections["total_rows_read"] >= 32
    assert len(sections["source_file_hash"]) == 64


def test_excel_loader_missing_file_raises():
    """Verify loader raises ExcelLoadError on missing file."""
    loader = ExcelLoader("non_existent_file.xlsx")
    with pytest.raises(ExcelLoadError):
        loader.load_raw_sections()


def test_ingestion_service_e2e_and_idempotency(tmp_path: Path):
    """Test full ingestion into temporary SQLite database and verify idempotency."""
    test_db_path = tmp_path / "test_price.db"
    sqlite_db = SQLiteDatabase(test_db_path)
    excel_path = settings.get_excel_path()

    # First ingestion run
    svc = IngestionService(sqlite_db=sqlite_db, vector_db=None, excel_path=excel_path)
    report1 = svc.run_ingestion()

    assert report1.status == "success"
    assert report1.materials_imported >= 20
    assert report1.labor_imported >= 5
    total = report1.materials_imported + report1.labor_imported
    assert report1.records_created == total
    assert report1.records_updated == 0

    # Verify counts in SQLite
    stats = sqlite_db.get_database_stats()
    assert stats["total_material_records"] == report1.materials_imported
    assert stats["total_labor_records"] == report1.labor_imported
    assert stats["total_records"] == total

    # Second ingestion run (Idempotency check without clean_rebuild)
    report2 = svc.run_ingestion()
    assert report2.status == "success"
    assert report2.records_created == 0
    assert report2.records_updated == total

    # Total records must not have duplicated
    stats_after = sqlite_db.get_database_stats()
    assert stats_after["total_records"] == total
