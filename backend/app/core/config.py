"""
Centralized configuration management.

All environment-specific values (API keys, model names, limits) are
read from environment variables / .env, never hardcoded. This keeps
the LLM provider swappable -- the graph code depends only on the
`get_chat_model()` factory below, not on a specific provider's SDK.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM provider ---
    # "groq" (default, free-tier friendly) or "google" (Gemini)
    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    google_api_key: str = ""
    google_model: str = "gemini-1.5-flash"

    llm_temperature: float = 0.2
    llm_max_retries: int = 3

    # --- search provider ---
    # If TAVILY_API_KEY is set, Tavily is used (recommended -- more
    # reliable than DDG on restricted networks). Otherwise falls back
    # to duckduckgo-search.
    tavily_api_key: str = ""

    # --- workflow tuning ---
    max_research_retries: int = 1
    max_search_results_per_query: int = 4

    # --- persistence ---
    # Postgres connection string for app tables (sessions, reports,
    # chat_messages, progress_events) -- see db.py.
    database_url: str = "postgresql://postgres:postgres@localhost:5432/zylabs"

    # Separate Postgres connection string for LangGraph checkpoints
    # (see checkpoint.py). Split from database_url so the two stores
    # can be scaled, backed up, or hosted independently -- checkpoint
    # writes are higher-frequency (per graph node) than app writes, and
    # checkpoint data is more disposable (sessions remain usable even
    # if checkpoint history is pruned/lost; reports/chat are not).
    # Defaults to the same instance/db as database_url if unset, so a
    # single-Postgres dev setup still works without extra config.
    checkpoint_database_url: str = ""

    # --- app ---
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def resolved_checkpoint_database_url(self) -> str:
        """checkpoint_database_url if set, else fall back to database_url."""
        return self.checkpoint_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor -- import this, not Settings() directly."""
    return Settings()


def get_chat_model():
    """
    Factory that returns a LangChain chat model based on configured
    provider. Keeps every node provider-agnostic: nodes call
    `get_chat_model()` and never import a provider SDK directly.
    """
    settings = get_settings()

    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=settings.llm_temperature,
            max_retries=settings.llm_max_retries,
        )

    if settings.llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            google_api_key=settings.google_api_key,
            model=settings.google_model,
            temperature=settings.llm_temperature,
            max_retries=settings.llm_max_retries,
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")