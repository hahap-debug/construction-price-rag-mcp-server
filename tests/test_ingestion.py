"""Unit tests for Excel Data Ingestion Pipeline."""

from pathlib import Path
import pytest
from app.config import settings
from app.database.sqlite_db import SQLiteDatabase
from app.ingestion.excel_loader import ExcelLoader, ExcelLoadError
from app.ingestion.ingestion_service import IngestionService


def test_excel_loader_reads_designated_sheet():
    """Verify loader reads 3 worksheets and extracts element, material, and labor row counts."""
    excel_path = settings.get_excel_path()
    loader = ExcelLoader(excel_path)
    sections = loader.load_raw_sections()

    assert "Element-based" in sections["worksheet_name"]
    assert len(sections["elements"]) >= 500
    assert len(sections["materials"]) >= 400
    assert len(sections["labor"]) >= 200
    assert sections["total_rows_read"] >= 1000
    assert len(sections["source_file_hash"]) == 64


def test_excel_loader_missing_file_raises():
    """Verify loader raises ExcelLoadError on missing file."""
    loader = ExcelLoader("non_existent_file.xlsx")
    with pytest.raises(ExcelLoadError):
        loader.load_raw_sections()


def test_excel_loader_search_priority(monkeypatch, tmp_path: Path):
    """Verify search priority: 1. Desktop -> 2. data/ project folder -> 3. Downloads."""
    fake_desktop = tmp_path / "Desktop"
    fake_downloads = tmp_path / "Downloads"
    fake_desktop.mkdir()
    fake_downloads.mkdir()

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    # 1. File only in Downloads
    dl_file = fake_downloads / "test_p_unique.xlsx"
    dl_file.write_text("fake_content", encoding="utf-8")
    resolved = ExcelLoader.resolve_excel_path("test_p_unique.xlsx")
    assert resolved == dl_file.resolve()

    # 2. File in Desktop as well -> Desktop must win
    dt_file = fake_desktop / "test_p_unique.xlsx"
    dt_file.write_text("fake_content", encoding="utf-8")
    resolved2 = ExcelLoader.resolve_excel_path("test_p_unique.xlsx")
    assert resolved2 == dt_file.resolve()


def test_ingestion_service_e2e_and_idempotency(tmp_path: Path):
    """Test full ingestion into temporary SQLite database and verify idempotency."""
    test_db_path = tmp_path / "test_price.db"
    sqlite_db = SQLiteDatabase(test_db_path)
    excel_path = settings.get_excel_path()

    # First ingestion run
    svc = IngestionService(sqlite_db=sqlite_db, vector_db=None, excel_path=excel_path)
    report1 = svc.run_ingestion()

    assert report1.status == "success"
    assert report1.elements_imported >= 500
    assert report1.materials_imported >= 400
    assert report1.labor_imported >= 200
    total = report1.elements_imported + report1.materials_imported + report1.labor_imported
    assert report1.records_created == total
    assert report1.records_updated == 0

    # Verify counts in SQLite
    stats = sqlite_db.get_database_stats()
    assert stats["total_element_records"] == report1.elements_imported
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
