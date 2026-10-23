"""Application settings, loaded from environment variables (prefix DEVPILOT_)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEVPILOT_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./devpilot.db"
    data_dir: Path = Path("./data")
    # Fernet key used to encrypt GitHub tokens at rest. Required outside development.
    secret_key: str = ""
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:5173"

    # Ingestion limits
    max_upload_bytes: int = 50 * 1024 * 1024
    max_repo_bytes: int = 200 * 1024 * 1024
    max_file_bytes: int = 512 * 1024
    max_files: int = 20_000
    # Local-path ingestion is only allowed beneath these directories (";"-separated).
    # Empty = disabled.
    allowed_local_roots: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    retention_days: int = 14

    # LLM
    llm_provider: str = "anthropic"  # "anthropic" | "ollama" | "none"
    llm_model: str = "claude-opus-5-5"  # Anthropic model ID
    llm_effort: str = "medium"
    llm_timeout_s: float = 120.0
    llm_max_context_chars: int = 60_000
    # Phase 3 switches, chosen by evaluation (docs/evaluation.md). v1/changed is the original.
    llm_prompt_version: str = "v1"  # "v1" | "v2"  (app/ai/context.py PROMPTS)
    llm_context: str = "changed"  # "changed": changed files only | "repo": plus related code
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    # Local models via Ollama. Admin-set only; users never supply this URL.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:3b"
    # Ollama's default context window is small and it truncates long prompts silently.
    ollama_num_ctx: int = 16384

    # GitHub App (optional): client id/secret of the App's user-authorization flow, and its URL
    # slug (github.com/apps/<slug>) for the "install on repositories" link.
    github_client_id: str = ""
    github_client_secret: str = ""
    github_app_slug: str = ""
    github_api_url: str = "https://api.github.com"

    # Background jobs
    run_worker_in_process: bool = True
    job_timeout_s: int = 600
    reviews_per_hour: int = 30

    @field_validator("allowed_local_roots", mode="before")
    @classmethod
    def _split_roots(cls, v: object) -> object:
        if isinstance(v, str):
            return [p for p in v.split(";") if p.strip()]
        return v

    @property
    def llm_configured(self) -> bool:
        # Ollama needs no credentials; whether it is running is checked when a review calls it.
        if self.llm_provider == "ollama":
            return True
        return self.llm_provider == "anthropic" and bool(self.anthropic_api_key)

    @property
    def active_llm_model(self) -> str:
        return self.ollama_model if self.llm_provider == "ollama" else self.llm_model

    @property
    def llm_is_local(self) -> bool:
        """True when reviewed code never leaves this machine."""
        host = urlparse(self.ollama_url).hostname
        return self.llm_provider == "ollama" and host in {"127.0.0.1", "localhost", "::1"}

    @property
    def context_chars(self) -> int:
        """Code budget for one review prompt. Ollama refuses prompts above 75% of num_ctx (about
        3.5 characters per token), so the budget shrinks to fit, keeping 12,000 characters for the
        system prompt, analyzer results and headers. Files that do not fit are omitted and listed."""
        if self.llm_provider == "ollama":
            return max(4_000, min(self.llm_max_context_chars, int(self.ollama_num_ctx * 0.75 * 3.5) - 12_000))
        return self.llm_max_context_chars

    @property
    def github_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.env != "development" and not s.secret_key:
        raise RuntimeError("DEVPILOT_SECRET_KEY must be set outside development")
    return s
