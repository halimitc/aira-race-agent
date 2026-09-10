import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load dotenv at module level
load_dotenv()

@dataclass(frozen=True)
class Config:
    # AGP Connection Settings
    # Automatically normalize /track/mcp to /track/mcp/sse if needed
    _raw_url: str = os.getenv("AGP_SERVER_URL", "https://api.agp.onlatch.com/track/mcp/sse").strip()
    agp_server_url: str = _raw_url if _raw_url.endswith("/sse") else f"{_raw_url.rstrip('/')}/sse"
    # Support both AGP_TOKEN and AUTH (from official MCP config snippet) and strip 'Bearer ' if present
    agp_token: str = (os.getenv("AGP_TOKEN") or os.getenv("AUTH") or "").replace("Bearer ", "").strip()

    # LLM Keys
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    anthropic_api_key: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    openrouter_api_key: Optional[str] = os.getenv("OPENROUTER_API_KEY")

    # LLM Settings
    llm_provider: str = os.getenv("REASONING_PROVIDER", os.getenv("LLM_PROVIDER", "openai")).lower()
    llm_model: str = (
        "grok-3-mini"
        if (os.getenv("OPENAI_API_KEY") or "").startswith("xai-") and ("openai/gpt" in os.getenv("LLM_MODEL", "") or not os.getenv("LLM_MODEL"))
        else os.getenv("LLM_MODEL", "qwen/qwen3.8-27b")
    )
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")  # Stable backup Gemini model
    openai_base_url: str = (
        "https://api.x.ai/v1"
        if (os.getenv("OPENAI_API_KEY") or "").startswith("xai-") and ("groq.com" in os.getenv("OPENAI_BASE_URL", "") or not os.getenv("OPENAI_BASE_URL"))
        else os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    )

    # Race Profile Strategy
    # Options: conservative, balanced, aggressive, ultra_aggressive
    race_profile: str = os.getenv("RACE_PROFILE", "balanced").lower()

    # Paths and Caching
    cache_dir: Path = field(default_factory=lambda: Path(os.getenv("CACHE_DIR", ".cache")))
    memory_file: Path = field(default_factory=lambda: Path(os.getenv("MEMORY_FILE", "memory.json")))
    learning_file: Path = field(default_factory=lambda: Path(os.getenv("LEARNING_FILE", "learning.json")))
    metrics_file: Path = field(default_factory=lambda: Path(os.getenv("METRICS_FILE", "metrics.json")))

    def __post_init__(self) -> None:
        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        """Validates critical config requirements."""
        if not self.agp_token or self.agp_token == "agpm_placeholder":
            raise ValueError(
                "AGP_TOKEN must be set in your .env file with a valid Latch token (e.g. agpm_...)"
            )
        
        # Verify provider keys
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY must be set in your .env file to use Gemini.")
        elif self.llm_provider == "claude" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set in your .env file to use Claude.")
        elif self.llm_provider in ("openai", "openai_compatible") and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY must be set in your .env file to use OpenAI / OpenAI Compatible provider.")
        elif self.llm_provider == "openrouter" and not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY must be set in your .env file to use OpenRouter.")

# Global config instance
config = Config()
