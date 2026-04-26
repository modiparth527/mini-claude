"""
Application config loaded from environment variables (or a .env file).

pydantic-settings validates types and gives clear errors when required vars
are missing — much better than bare os.environ.get() calls scattered through
the codebase.

Supported backends
──────────────────
  MODE=auto (default)
      Uses Anthropic API if ANTHROPIC_API_KEY is set, otherwise Bedrock.

  MODE=anthropic
      Direct Anthropic API.  Requires ANTHROPIC_API_KEY.
      Set MODEL to the Anthropic model ID, e.g. claude-sonnet-4-6.

  MODE=bedrock
      AWS Bedrock via your existing AWS credentials (SSO, env vars, ~/.aws).
      Run `aws sso login --profile <profile>` before starting.
      Set BEDROCK_MODEL to the cross-region inference profile ID.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Backend selection ─────────────────────────────────────────────────────
    # "auto"      → anthropic if ANTHROPIC_API_KEY is set, else bedrock
    # "anthropic" → direct Anthropic API (requires ANTHROPIC_API_KEY)
    # "bedrock"   → AWS Bedrock via SSO / env credentials
    mode: str = "auto"

    # ── Shared ────────────────────────────────────────────────────────────────
    max_tokens: int = 4096
    system_prompt: str = (
        "You are a concise, practical coding assistant. "
        "Use tools whenever they help answer the user's request. "
        "Prefer short, focused responses."
    )

    # ── Anthropic direct API ──────────────────────────────────────────────────
    # Model IDs: claude-sonnet-4-6 | claude-opus-4-7 | claude-haiku-4-5-20251001
    anthropic_api_key: str | None = None
    model: str = "claude-sonnet-4-6"

    # ── AWS Bedrock ───────────────────────────────────────────────────────────
    # Claude 4 models require the "us." cross-region inference profile prefix.
    # Model IDs: us.anthropic.claude-sonnet-4-6 | us.anthropic.claude-opus-4-7
    #            us.anthropic.claude-haiku-4-5-20251001-v1:0
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    bedrock_model: str = "us.anthropic.claude-sonnet-4-6"

    @property
    def active_mode(self) -> str:
        """Resolve 'auto' to a concrete backend based on available credentials."""
        if self.mode == "auto":
            return "anthropic" if self.anthropic_api_key else "bedrock"
        return self.mode

    @property
    def effective_model(self) -> str:
        """Return the model ID appropriate for the active backend."""
        return self.model if self.active_mode == "anthropic" else self.bedrock_model


settings = Settings()
