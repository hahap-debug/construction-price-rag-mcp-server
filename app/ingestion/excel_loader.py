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
    def resolve_excel_path(cls, file_path: str | Path | None = None) -> Path:
        """Resolve Excel path with strict search priority:
        1. Desktop (Path.home() / Desktop)
        2. Project data folder (PROJECT_ROOT / data)
        3. Downloads (Path.home() / Downloads)
        4. Explicit absolute path or project root
        """
        from app.config import PROJECT_ROOT

        # If explicit path provided and exists, honor it directly
        if file_path and str(file_path).strip():
            raw = Path(file_path)
            if raw.is_absolute() and raw.exists():
                return raw.resolve()
            # Search strictly for the user-specified filename
            names_to_search = [raw.name]
        else:
            # Default candidate filenames to search in priority order
            names_to_search = ["price_database.xlsx", "Real_Price_Database_3Worksheets-v2.xlsx"]

        # 1. Desktop (Highest Priority: Desktop / OneDrive Desktop)
        desktop_dirs = [
            Path.home() / "Desktop",
            Path.home() / "OneDrive" / "Desktop",
        ]
        for d in desktop_dirs:
            for name in names_to_search:
                cand = d / name
                try:
                    if cand.exists():
                        logger.info(f"Auto-resolved Excel file from Desktop: {cand}")
                        return cand.resolve()
                except (PermissionError, OSError):
                    pass

        # 2. Project data folder (Second Priority)
        data_dir = PROJECT_ROOT / "data"
        for name in names_to_search:
            cand = data_dir / name
            try:
                if cand.exists():
                    logger.info(f"Auto-resolved Excel file from project data/ folder: {cand}")
                    return cand.resolve()
            except (PermissionError, OSError):
                pass

        # 3. Downloads folder (Third Priority)
        downloads_dir = Path.home() / "Downloads"
        for name in names_to_search:
            cand = downloads_dir / name
            try:
                if cand.exists():
                    logger.info(f"Auto-resolved Excel file from Downloads folder: {cand}")
                    return cand.resolve()
            except (PermissionError, OSError):
                pass

        # 4. Project root / Current working directory
        for name in names_to_search:
            cand = PROJECT_ROOT / name
            if cand.exists():
                logger.info(f"Auto-resolved Excel file from project root: {cand}")
                return cand.resolve()
            cand_cwd = Path.cwd() / name
            if cand_cwd.exists():
                logger.info(f"Auto-resolved Excel file from CWD: {cand_cwd}")
                return cand_cwd.resolve()

        searched_dirs = [
            str(Path.home() / "Desktop"),
            str(PROJECT_ROOT / "data"),
            str(Path.home() / "Downloads"),
            str(PROJECT_ROOT),
        ]
        searched_text = "\n - " + "\n - ".join(searched_dirs)
        raise ExcelLoadError(
            f"ไม่พบไฟล์ '{file_path or file_name}'\nระบบค้นหาตามลำดับความสำคัญแล้วแต่ไม่พบ (1. Desktop -> 2. data/ -> 3. Downloads):{searched_text}"
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

    @staticmethod
    def _extract_sheet_table(ws: Any, section_name: str) -> list[dict[str, Any]]:
        """Extract rows from a structured worksheet (header row contains 'รายการ' and 'หน่วย')."""
        start_row = 5
        for r in range(1, min(10, ws.max_row + 1)):
            c1 = str(ws.cell(r, 1).value or "").strip()
            c2 = str(ws.cell(r, 2).value or "").strip()
            if ("รายการ" in c1 or "Item" in c1) and ("หน่วย" in c2 or "Unit" in c2):
                start_row = r + 1
                break

        rows: list[dict[str, Any]] = []
        for r in range(start_row, ws.max_row + 1):
            row_vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
            first_val = str(row_vals[0] or "").strip() if row_vals[0] is not None else ""
            if not first_val or first_val.startswith("หมายเหตุ:"):
                continue

            price_val = row_vals[2] if len(row_vals) > 2 else None
            if price_val is not None and str(price_val).strip() != "":
                rows.append({
                    "row_index": r,
                    "raw_item_name": row_vals[0],
                    "raw_unit": row_vals[1] if len(row_vals) > 1 else "",
                    "raw_price": price_val,
                    "raw_note": row_vals[3] if len(row_vals) > 3 else "",
                    "raw_range": row_vals[4] if len(row_vals) > 4 else None,
                    "section": section_name,
                })
        return rows

    def load_raw_sections(self) -> dict[str, Any]:
        """Load worksheet(s) and separate element, material, and labor rows.

        Supports both 3-worksheet format ('Element-based', 'Material-based', 'ค่าแรงงาน')
        and legacy single-worksheet format ('วัสดุพื้นฐาน').

        Returns:
            Dictionary containing metadata, element rows, material rows, and labor rows.
        """
        # Resolve and validate path
        self.file_path = self.resolve_excel_path(self.file_path)
        self.validate_excel_file(self.file_path)

        try:
            wb = openpyxl.load_workbook(str(self.file_path), data_only=True)
        except Exception as e:
            raise ExcelLoadError(f"ไม่สามารถเปิดไฟล์ Excel '{self.file_path.name}' ได้ (ไฟล์อาจเสียหายหรือถูกล็อค): {e}") from e

        file_hash = self.calculate_file_hash()

        # Check if 3-worksheet mode applies
        multi_sheets = [s for s in wb.sheetnames if s in ("Element-based", "Material-based", "ค่าแรงงาน")]
        is_multi = len(multi_sheets) > 0 and self.sheet_name is None

        element_rows: list[dict[str, Any]] = []
        material_rows: list[dict[str, Any]] = []
        labor_rows: list[dict[str, Any]] = []
        total_rows_read = 0

        if is_multi:
            worksheet_names = []
            if "Element-based" in wb.sheetnames:
                ws_ele = wb["Element-based"]
                element_rows = self._extract_sheet_table(ws_ele, "element")
                total_rows_read += ws_ele.max_row
                worksheet_names.append("Element-based")
            if "Material-based" in wb.sheetnames:
                ws_mat = wb["Material-based"]
                material_rows = self._extract_sheet_table(ws_mat, "material")
                total_rows_read += ws_mat.max_row
                worksheet_names.append("Material-based")
            if "ค่าแรงงาน" in wb.sheetnames:
                ws_lab = wb["ค่าแรงงาน"]
                labor_rows = self._extract_sheet_table(ws_lab, "labor")
                total_rows_read += ws_lab.max_row
                worksheet_names.append("ค่าแรงงาน")

            worksheet_name = ", ".join(worksheet_names)
            first_ws = wb[worksheet_names[0]]
            title_text = str(first_ws.cell(1, 1).value or "").strip()
            header_note = str(first_ws.cell(2, 1).value or "").strip()

        else:
            # Single worksheet mode (either specified sheet or TARGET_WORKSHEET)
            target_sheet = self.sheet_name or self.TARGET_WORKSHEET
            if target_sheet not in wb.sheetnames:
                available = ", ".join(f"'{s}'" for s in wb.sheetnames)
                raise ExcelLoadError(
                    f"ไฟล์ Excel '{self.file_path.name}' ไม่มี Worksheet ชื่อ '{target_sheet}' "
                    f"(Worksheet ที่พบในไฟล์: {available})"
                )

            ws = wb[target_sheet]
            worksheet_name = target_sheet
            total_rows_read = ws.max_row
            title_text = str(ws.cell(1, 1).value or "").strip()
            header_note = str(ws.cell(2, 1).value or "").strip()

            if target_sheet == "Element-based":
                element_rows = self._extract_sheet_table(ws, "element")
            elif target_sheet == "Material-based":
                material_rows = self._extract_sheet_table(ws, "material")
            elif target_sheet == "ค่าแรงงาน":
                labor_rows = self._extract_sheet_table(ws, "labor")
            else:
                # Legacy single sheet parsing with section delimiters
                current_section: str | None = None
                for r in range(1, ws.max_row + 1):
                    row_vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
                    first_val = str(row_vals[0] or "").strip() if row_vals[0] is not None else ""

                    if "รายการวัสดุ" in first_val:
                        current_section = "material"
                        continue
                    elif "ค่าแรงงานพื้นฐาน" in first_val or "รายการค่าแรง" in first_val:
                        current_section = "labor"
                        continue
                    elif first_val.startswith("หมายเหตุ:"):
                        current_section = None
                        continue

                    if current_section == "material":
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
            f"Extracted {len(element_rows)} element rows, {len(material_rows)} material rows, "
            f"and {len(labor_rows)} labor rows from '{worksheet_name}' "
            f"(hash: {file_hash[:8]}...)"
        )

        return {
            "source_file": self.file_path.name,
            "source_path": str(self.file_path),
            "worksheet_name": worksheet_name,
            "source_file_hash": file_hash,
            "title_text": title_text,
            "header_note": header_note,
            "elements": element_rows,
            "materials": material_rows,
            "labor": labor_rows,
            "total_rows_read": total_rows_read,
        }
