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

    # --- persistence (sqlite) ---
    database_path: str = "./data/app.db"
    checkpoint_db_path: str = "./data/checkpoints.sqlite"

    # --- persistence (postgresql) ---
    database_url: str = ""

    # --- app ---
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"


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