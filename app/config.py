"""Configuration Management for Construction Price RAG MCP Server."""

from pathlib import Path
import logging
import sys
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """Application Settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ingestion & Data Sources
    excel_file_path: str = Field(
        default="price_database.xlsx",
        description="Path or filename to the Excel file containing price data",
    )
    excel_worksheet: str = Field(
        default="Element-based",
        description="Target primary worksheet name",
    )

    # Database
    use_desktop_storage: bool = Field(
        default=True,
        description="Whether to store database and FAISS index on user Desktop folder",
    )
    desktop_folder_name: str = Field(
        default="price_database",
        description="Folder name on user Desktop for database storage",
    )
    sqlite_db_path: str = Field(
        default="data/price.db",
        description="Path to SQLite database file",
    )
    faiss_index_dir: str = Field(
        default="data/faiss_index",
        description="Directory for FAISS index and metadata storage",
    )
    chroma_persist_directory: str = Field(
        default="data/chroma_db",
        description="Directory for legacy ChromaDB storage (deprecated)",
    )
    chroma_collection_name: str = Field(
        default="construction_prices",
        description="Name of the ChromaDB collection",
    )

    # Retrieval & Search
    enable_semantic_search: bool = Field(
        default=True,
        description="Whether semantic search is enabled",
    )
    embedding_provider: str = Field(
        default="chroma_default",
        description="Embedding provider: chroma_default or sentence_transformers",
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Model identifier for embeddings",
    )
    default_similarity_threshold: float = Field(
        default=0.35,
        description="Minimum score threshold for non-exact candidate results",
    )
    rrf_k: int = Field(
        default=60,
        description="Smoothing constant for Reciprocal Rank Fusion",
    )

    # MCP & Server
    mcp_transport: str = Field(
        default="stdio",
        description="Transport mode for FastMCP server: stdio, sse, or streamable-http",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )

    def get_desktop_dir(self) -> Path:
        """Resolve desktop folder for database storage with graceful local fallback."""
        desktop_dir = Path.home() / "Desktop" / self.desktop_folder_name
        try:
            desktop_dir.mkdir(parents=True, exist_ok=True)
            return desktop_dir
        except (PermissionError, OSError) as e:
            logger.warning(f"Could not access Desktop directory '{desktop_dir}': {e}. Falling back to local data directory.")
            fallback = PROJECT_ROOT / "data"
            return fallback

    def get_sqlite_path(self) -> Path:
        """Resolve SQLite path on Desktop price_database folder or configured path."""
        if self.use_desktop_storage:
            return self.get_desktop_dir() / "price.db"
        p = Path(self.sqlite_db_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def get_faiss_dir(self) -> Path:
        """Resolve FAISS directory on Desktop price_database folder or configured path."""
        if self.use_desktop_storage:
            faiss_p = self.get_desktop_dir() / "faiss_index"
            faiss_p.mkdir(parents=True, exist_ok=True)
            return faiss_p
        p = Path(self.faiss_index_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def get_chroma_dir(self) -> Path:
        """Resolve Chroma directory against project root if relative."""
        p = Path(self.chroma_persist_directory)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def get_excel_path(self) -> Path:
        """Resolve Excel path with strict priority: 1. Desktop, 2. data/ project folder, 3. Downloads."""
        from app.ingestion.excel_loader import ExcelLoader
        try:
            return ExcelLoader.resolve_excel_path(self.excel_file_path)
        except Exception:
            fallback = PROJECT_ROOT / "data" / "price_database.xlsx"
            if fallback.exists():
                return fallback
            return PROJECT_ROOT / "data" / "Real_Price_Database_3Worksheets-v2.xlsx"


settings = AppSettings()


def setup_logging() -> logging.Logger:
    """Configure application logging to write strictly to stderr.
    
    Writing to stdout corrupts stdio MCP protocol communication!
    """
    logger = logging.getLogger("construction_price_rag")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)
    return logger


logger = setup_logging()
