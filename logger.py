import logging
import sys
import os
from rich.logging import RichHandler

# Force UTF-8 output on Windows terminals
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape sequences on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def setup_logger(name: str = "agp-agent", level: int = logging.INFO) -> logging.Logger:
    """Configures structured logging using the Rich library."""
    from rich.console import Console
    console = Console(safe_box=True)
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)]
    )
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Suppress verbose httpx logs to keep console output clean
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return logger

# Global logger instance
logger = setup_logger()

