"""Construction Price RAG MCP Server Entry Point."""

from pathlib import Path
import os
import sys

# Ensure project root is in sys.path and is the active working directory
# This guarantees flawless execution when launched externally by MCP clients like Claude Desktop
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Prevent FastMCP from attempting to check for updates over network (causes hangs in sandboxed/offline environments)
os.environ["FASTMCP_CHECK_FOR_UPDATES"] = "off"

from fastmcp import FastMCP
from app.config import logger, settings
from app.database.sqlite_db import SQLiteDatabase
from app.ingestion.ingestion_service import IngestionService
from app.services.price_service import PriceService
from app.tools.price_tools import register_price_tools


def create_server() -> FastMCP:
    """Create and configure the FastMCP Construction Price Server."""
    # Ensure database is initialized and seeded if empty
    sqlite_db = SQLiteDatabase(settings.get_sqlite_path())
    stats = sqlite_db.get_database_stats()
    if stats["total_records"] == 0:
        logger.info("Database is empty on server startup. Triggering initial ingestion...")
        ingestion_svc = IngestionService(sqlite_db=sqlite_db)
        report = ingestion_svc.run_ingestion()
        logger.info(f"Initial ingestion finished: {report.status} ({report.records_created} records created)")

    # Initialize FastMCP Server
    mcp = FastMCP(
        name="construction-price-server",
        instructions=(
            "Construction Material and Labor Price Retrieval Server. "
            "Provides accurate, factual prices from verified market benchmarks for BIM and BOQ estimation."
        ),
    )

    # Initialize Service and Register Tools
    price_service = PriceService(sqlite_db=sqlite_db)
    register_price_tools(mcp=mcp, service=price_service)

    return mcp


# Global server instance for CLI / MCP client runners
mcp = create_server()


if __name__ == "__main__":
    logger.info(f"Starting Construction Price MCP Server via transport: {settings.mcp_transport}")
    # Run the server using configured transport (defaults to stdio)
    mcp.run(transport=settings.mcp_transport, show_banner=False)
