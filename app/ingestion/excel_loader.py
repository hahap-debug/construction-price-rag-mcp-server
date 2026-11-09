"""Excel Loader for Construction Price Database."""

from pathlib import Path
from typing import Any
import hashlib
import openpyxl

from app.config import logger


class ExcelLoadError(Exception):
    """Exception raised when loading or validating the Excel file fails."""
    pass


class ExcelLoader:
    """Loads and extracts raw records from the designated Excel worksheet ('วัสดุพื้นฐาน')."""

    TARGET_WORKSHEET = "วัสดุพื้นฐาน"

    def __init__(self, file_path: str | Path, sheet_name: str | None = None):
        self.raw_path = Path(file_path)
        self.file_path = self.raw_path
        self.sheet_name = sheet_name

    @classmethod
    def resolve_excel_path(cls, file_path: str | Path) -> Path:
        """Resolve Excel path with smart auto-detection, prioritizing Desktop."""
        raw = Path(file_path)

        # 1. Direct match (absolute path or relative to current working directory)
        if raw.exists():
            return raw.resolve()

        file_name = raw.name
        from app.config import PROJECT_ROOT

        # 2. Candidate search locations (Desktop prioritized for user drops)
        desktop_paths = [
            Path.home() / "Desktop" / file_name,
            Path.home() / "OneDrive" / "Desktop" / file_name,
        ]
        other_candidates = [
            Path.home() / "Downloads" / file_name,
            PROJECT_ROOT / "data" / file_name,
            PROJECT_ROOT / file_name,
            PROJECT_ROOT / raw,
        ]

        candidates = desktop_paths + other_candidates
        for cand in candidates:
            if cand.exists():
                logger.info(f"Auto-resolved Excel file '{file_name}' to: {cand}")
                return cand.resolve()

        searched_dirs = [
            str(Path.home() / "Desktop"),
            str(Path.home() / "Downloads"),
            str(PROJECT_ROOT / "data"),
            str(PROJECT_ROOT),
        ]
        searched_text = "\n - " + "\n - ".join(searched_dirs)
        raise ExcelLoadError(
            f"ไม่พบไฟล์ '{file_path}'\nระบบค้นหาในโฟลเดอร์ต่อไปนี้แล้วแต่ไม่พบ:{searched_text}"
        )

    @classmethod
    def validate_excel_file(cls, path: Path) -> None:
        """Verify that the target file has a valid Excel extension."""
        if path.suffix.lower() not in (".xlsx", ".xls"):
            raise ExcelLoadError(
                f"ไฟล์ '{path.name}' ไม่ใช่ไฟล์ Excel (.xlsx หรือ .xls) แต่เป็นนามสกุล '{path.suffix}'"
            )

    def calculate_file_hash(self) -> str:
        """Calculate SHA-256 hash of the source Excel file for provenance tracking."""
        if not self.file_path.exists():
            raise ExcelLoadError(f"File not found: {self.file_path}")
        hasher = hashlib.sha256()
        with open(self.file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def load_raw_sections(self) -> dict[str, Any]:
        """Load worksheet 'วัสดุพื้นฐาน' and separate material and labor rows.

        Returns:
            Dictionary containing metadata, material rows, and labor rows.
        """
        # Resolve and validate path
        self.file_path = self.resolve_excel_path(self.file_path)
        self.validate_excel_file(self.file_path)

        try:
            wb = openpyxl.load_workbook(str(self.file_path), data_only=True)
        except Exception as e:
            raise ExcelLoadError(f"ไม่สามารถเปิดไฟล์ Excel '{self.file_path.name}' ได้ (ไฟล์อาจเสียหายหรือถูกล็อค): {e}") from e

        # Strict check for target worksheet (default 'วัสดุพื้นฐาน')
        target_sheet = self.sheet_name or self.TARGET_WORKSHEET
        if target_sheet not in wb.sheetnames:
            available = ", ".join(f"'{s}'" for s in wb.sheetnames)
            raise ExcelLoadError(
                f"ไฟล์ Excel '{self.file_path.name}' ไม่มี Worksheet ชื่อ '{target_sheet}' "
                f"(Worksheet ที่พบในไฟล์: {available})"
            )

        ws = wb[target_sheet]
        worksheet_name = target_sheet

        file_hash = self.calculate_file_hash()
        logger.info(
            f"Loaded worksheet '{worksheet_name}' from {self.file_path.name} "
            f"(rows: {ws.max_row}, cols: {ws.max_column}, hash: {file_hash[:8]}...)"
        )

        # Extract title and subtitle notes
        title_text = str(ws.cell(1, 1).value or "").strip()
        header_note = str(ws.cell(2, 1).value or "").strip()

        material_rows: list[dict[str, Any]] = []
        labor_rows: list[dict[str, Any]] = []

        current_section: str | None = None

        for r in range(1, ws.max_row + 1):
            row_vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
            first_val = str(row_vals[0] or "").strip() if row_vals[0] is not None else ""

            # Check section transitions
            if "รายการวัสดุ" in first_val:
                current_section = "material"
                continue
            elif "ค่าแรงงานพื้นฐาน" in first_val or "รายการค่าแรง" in first_val:
                current_section = "labor"
                continue
            elif first_val.startswith("หมายเหตุ:"):
                # Footer note reached
                current_section = None
                continue

            # Check if this row is a valid data row (must have item name and price)
            if current_section == "material":
                # Must have col 1 (item name) and col 3 (price)
                if row_vals[0] and row_vals[2] is not None:
                    material_rows.append({
                        "row_index": r,
                        "raw_item_name": row_vals[0],
                        "raw_unit": row_vals[1],
                        "raw_price": row_vals[2],
                        "raw_note": row_vals[3],
                        "raw_range": row_vals[4] if len(row_vals) > 4 else None,
                        "section": "material",
                    })

            elif current_section == "labor":
                if row_vals[0] and row_vals[2] is not None:
                    labor_rows.append({
                        "row_index": r,
                        "raw_item_name": row_vals[0],
                        "raw_unit": row_vals[1],
                        "raw_price": row_vals[2],
                        "raw_note": row_vals[3],
                        "raw_range": row_vals[4] if len(row_vals) > 4 else None,
                        "section": "labor",
                    })

        logger.info(
            f"Extracted {len(material_rows)} material rows and {len(labor_rows)} labor rows "
            f"from '{worksheet_name}'"
        )

        return {
            "source_file": self.file_path.name,
            "source_path": str(self.file_path),
            "worksheet_name": worksheet_name,
            "source_file_hash": file_hash,
            "title_text": title_text,
            "header_note": header_note,
            "materials": material_rows,
            "labor": labor_rows,
            "total_rows_read": ws.max_row,
        }
