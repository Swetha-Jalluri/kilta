"""Settings, read from the environment (.env is loaded by `main()`, never by tests)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mcp_url: str = "http://localhost:8765/mcp"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Chain order: Gemini Flash -> Groq -> Gemini Flash-Lite -> Ollama.
    model_primary: str = "gemini-3.5-flash"
    model_groq: str = "openai/gpt-oss-120b"
    model_fallback: str = "gemini-3.5-flash-lite"
    ollama_model: str = "qwen3:8b"
    ollama_host: str = "http://localhost:11434"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    demo_mode: bool = True
    data_dir: Path = REPO_ROOT / "data"
    docs_dir: Path = REPO_ROOT / "docs"
    groq_first_token_timeout: float = 60.0  # Groq's free tier 429s are retried by its client
    retries: int = 2  # per model, for 429 / 5xx / timeouts
    retry_base_delay: float = 1.0
    first_token_timeout: float = 20.0
    min_model_interval: float = 0.0  # pacing between model calls, for free-tier limits
    model_cooldown: float = 45.0  # skip a model this long after it failed
    turn_timeout: float = 120.0
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        d = cls()
        return cls(
            mcp_url=e.get("KILTA_MCP_URL", d.mcp_url),
            gemini_api_key=e.get("GEMINI_API_KEY", ""),
            groq_api_key=e.get("GROQ_API_KEY", ""),
            model_primary=e.get("KILTA_MODEL_PRIMARY", d.model_primary),
            model_groq=e.get("KILTA_MODEL_GROQ", d.model_groq),
            model_fallback=e.get("KILTA_MODEL_FALLBACK", d.model_fallback),
            ollama_model=e.get("KILTA_OLLAMA_MODEL", d.ollama_model),
            ollama_host=e.get("OLLAMA_HOST", d.ollama_host),
            demo_mode=_bool(e.get("KILTA_DEMO_MODE"), d.demo_mode),
            data_dir=Path(e["KILTA_DATA_DIR"]) if e.get("KILTA_DATA_DIR") else d.data_dir,
            retries=int(e.get("KILTA_MODEL_RETRIES", d.retries)),
            retry_base_delay=float(e.get("KILTA_MODEL_RETRY_DELAY", d.retry_base_delay)),
            first_token_timeout=float(e.get("KILTA_MODEL_TIMEOUT", d.first_token_timeout)),
            min_model_interval=float(e.get("KILTA_MODEL_MIN_INTERVAL", d.min_model_interval)),
            model_cooldown=float(e.get("KILTA_MODEL_COOLDOWN", d.model_cooldown)),
        )
