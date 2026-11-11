"""SQLite Database Layer - Primary Source of Truth for Construction Prices."""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.config import logger
from app.schemas.price_record import PriceRecord


class SQLiteDatabase:
    """Manages SQLite storage for construction price records and metadata."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from app.config import settings
            self.db_path = settings.get_sqlite_path()
        else:
            p = Path(db_path)
            if p.is_absolute():
                self.db_path = p
            else:
                from app.config import PROJECT_ROOT, settings
                if (PROJECT_ROOT / p).exists():
                    self.db_path = PROJECT_ROOT / p
                elif settings.get_sqlite_path().exists() and p.name == "price.db":
                    self.db_path = settings.get_sqlite_path()
                else:
                    self.db_path = PROJECT_ROOT / p

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Create and return a configured sqlite3 connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable foreign keys and WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize_schema(self) -> None:
        """Create database tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Price records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prices (
                    price_id TEXT PRIMARY KEY,
                    record_type TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    normalized_item_name TEXT NOT NULL,
                    bim_family TEXT,
                    bim_type TEXT,
                    category TEXT,
                    description TEXT,
                    unit TEXT NOT NULL,
                    normalized_unit TEXT NOT NULL,
                    unit_price TEXT NOT NULL,
                    market_min TEXT,
                    market_max TEXT,
                    currency TEXT NOT NULL DEFAULT 'THB',
                    price_date TEXT,
                    source_name TEXT,
                    source_url TEXT,
                    source_note TEXT,
                    vat_included INTEGER,
                    transportation_included INTEGER,
                    original_excel_row INTEGER NOT NULL,
                    raw_source_data TEXT,
                    imported_at TEXT NOT NULL
                )
            """)

            # Ensure columns exist if table was previously created without them
            cursor.execute("PRAGMA table_info(prices)")
            existing_cols = [col["name"] for col in cursor.fetchall()]
            if "bim_family" not in existing_cols:
                cursor.execute("ALTER TABLE prices ADD COLUMN bim_family TEXT")
            if "bim_type" not in existing_cols:
                cursor.execute("ALTER TABLE prices ADD COLUMN bim_type TEXT")

            # Indexes for efficient filtering and exact lookup
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_record_type ON prices(record_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_unit ON prices(unit)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_normalized_unit ON prices(normalized_unit)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(price_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_item_name ON prices(normalized_item_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_bim_family ON prices(bim_family)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_bim_type ON prices(bim_type)")

            # Ingestion metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

        logger.debug(f"SQLite schema initialized at {self.db_path}")

    def upsert_price(self, record: PriceRecord) -> bool:
        """Insert or update a price record idempotently.

        Returns:
            True if inserted as new record, False if updated existing record.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT price_id FROM prices WHERE price_id = ?", (record.price_id,))
            exists = cursor.fetchone() is not None

            cursor.execute("""
                INSERT INTO prices (
                    price_id, record_type, item_name, normalized_item_name,
                    bim_family, bim_type, category, description,
                    unit, normalized_unit, unit_price, market_min, market_max,
                    currency, price_date, source_name, source_url, source_note,
                    vat_included, transportation_included,
                    original_excel_row, raw_source_data, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(price_id) DO UPDATE SET
                    record_type = excluded.record_type,
                    item_name = excluded.item_name,
                    normalized_item_name = excluded.normalized_item_name,
                    bim_family = excluded.bim_family,
                    bim_type = excluded.bim_type,
                    category = excluded.category,
                    description = excluded.description,
                    unit = excluded.unit,
                    normalized_unit = excluded.normalized_unit,
                    unit_price = excluded.unit_price,
                    market_min = excluded.market_min,
                    market_max = excluded.market_max,
                    currency = excluded.currency,
                    price_date = excluded.price_date,
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    source_note = excluded.source_note,
                    vat_included = excluded.vat_included,
                    transportation_included = excluded.transportation_included,
                    original_excel_row = excluded.original_excel_row,
                    raw_source_data = excluded.raw_source_data,
                    imported_at = excluded.imported_at
            """, (
                record.price_id,
                record.record_type,
                record.item_name,
                record.normalized_item_name,
                getattr(record, "bim_family", None),
                getattr(record, "bim_type", None),
                record.category,
                record.description,
                record.unit,
                record.normalized_unit,
                str(record.unit_price),
                str(record.market_min) if record.market_min is not None else None,
                str(record.market_max) if record.market_max is not None else None,
                record.currency,
                record.price_date.isoformat() if record.price_date else None,
                record.source_name,
                record.source_url,
                record.source_note,
                1 if record.vat_included else (0 if record.vat_included is False else None),
                1 if record.transportation_included else (0 if record.transportation_included is False else None),
                record.original_excel_row,
                json.dumps(record.raw_source_data, ensure_ascii=False),
                record.imported_at.isoformat(),
            ))
            conn.commit()
            return not exists

    def _row_to_model(self, row: sqlite3.Row) -> PriceRecord:
        """Convert a SQLite row to a validated PriceRecord Pydantic instance."""
        price_date_val = None
        if row["price_date"]:
            price_date_val = date.fromisoformat(row["price_date"])

        vat_val = None
        if row["vat_included"] is not None:
            vat_val = bool(row["vat_included"])

        trans_val = None
        if row["transportation_included"] is not None:
            trans_val = bool(row["transportation_included"])

        raw_data = {}
        if row["raw_source_data"]:
            try:
                raw_data = json.loads(row["raw_source_data"])
            except json.JSONDecodeError:
                raw_data = {}

        return PriceRecord(
            price_id=row["price_id"],
            record_type=row["record_type"],
            item_name=row["item_name"],
            normalized_item_name=row["normalized_item_name"],
            bim_family=row["bim_family"] if "bim_family" in row.keys() else None,
            bim_type=row["bim_type"] if "bim_type" in row.keys() else None,
            category=row["category"],
            description=row["description"],
            unit=row["unit"],
            normalized_unit=row["normalized_unit"],
            unit_price=Decimal(row["unit_price"]),
            market_min=Decimal(row["market_min"]) if row["market_min"] else None,
            market_max=Decimal(row["market_max"]) if row["market_max"] else None,
            currency=row["currency"],
            price_date=price_date_val,
            source_name=row["source_name"],
            source_url=row["source_url"],
            source_note=row["source_note"],
            vat_included=vat_val,
            transportation_included=trans_val,
            original_excel_row=row["original_excel_row"],
            raw_source_data=raw_data,
            imported_at=datetime.fromisoformat(row["imported_at"]),
        )

    def get_price_by_id(self, price_id: str) -> PriceRecord | None:
        """Retrieve a single price record by price_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM prices WHERE price_id = ?", (price_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_model(row)
            return None

    def get_all_prices(self, record_type: str | None = None) -> list[PriceRecord]:
        """Retrieve all price records, optionally filtered by record_type."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if record_type and record_type != "all":
                cursor.execute(
                    "SELECT * FROM prices WHERE record_type = ? ORDER BY price_id",
                    (record_type,),
                )
            else:
                cursor.execute("SELECT * FROM prices ORDER BY price_id")

            return [self._row_to_model(r) for r in cursor.fetchall()]

    def filter_prices(
        self,
        record_type: str | None = None,
        unit: str | None = None,
        as_of: date | None = None,
    ) -> list[PriceRecord]:
        """Filter price records by record type, unit, and effective date."""
        query = "SELECT * FROM prices WHERE 1=1"
        params: list[Any] = []

        if record_type and record_type != "all":
            query += " AND record_type = ?"
            params.append(record_type)

        if unit:
            query += " AND (unit = ? OR normalized_unit = ?)"
            params.extend([unit, unit])

        if as_of:
            query += " AND (price_date IS NULL OR price_date <= ?)"
            params.append(as_of.isoformat())

        query += " ORDER BY price_id"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [self._row_to_model(r) for r in cursor.fetchall()]

    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata key-value pair."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (key, value, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def get_metadata(self, key: str) -> str | None:
        """Get a metadata value by key."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def clear_all_records(self) -> None:
        """Clear all price records and metadata from the database for a clean rebuild."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM prices")
            cursor.execute("DELETE FROM metadata")
            conn.commit()
            cursor.execute("VACUUM")
        logger.info(f"Cleared all records from SQLite database at {self.db_path}")

    def get_database_stats(self) -> dict[str, Any]:
        """Get summary statistics of the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt FROM prices WHERE record_type = 'element'")
            ele_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) AS cnt FROM prices WHERE record_type = 'material'")
            mat_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) AS cnt FROM prices WHERE record_type = 'labor'")
            lab_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT MAX(price_date) AS max_date FROM prices")
            max_date = cursor.fetchone()["max_date"]

            return {
                "total_element_records": ele_count,
                "total_material_records": mat_count,
                "total_labor_records": lab_count,
                "total_records": ele_count + mat_count + lab_count,
                "latest_price_date": max_date,
            }
