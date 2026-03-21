"""
Configuration management.
Loads from .env file and validates all settings.
"""

from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # --- GPU ---
    DEVICE: str = "auto"

    # --- Embedding ---
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # --- Ollama ---
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "mistral:7b-instruct-q4_K_M"

    # --- Sarvam AI ---
    SARVAM_API_KEY: str = ""
    LLM_PROVIDER: str = "auto"  # "sarvam" | "ollama" | "fallback" | "auto"

    # --- ChromaDB ---
    CHROMA_PERSIST_DIR: str = "./vectorstore"
    CHROMA_COLLECTION_NAME: str = "resumes"

    # --- Resume Processing ---
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50
    MAX_RESUME_SIZE_MB: int = 10
    SUPPORTED_FORMATS: str = ".pdf,.docx"

    # --- Matching ---
    TOP_K_CANDIDATES: int = 10
    MIN_MATCH_SCORE: float = 0.35

    # --- Interview Agent ---
    INTERVIEW_BASE_URL: str = ""  # e.g. https://your-frontend.com/candidate/interview

    # --- CORS ---
    CORS_ORIGINS: str = "*"  # comma-separated list of allowed origins, or "*"

    # --- Email (Gmail SMTP) ---
    GMAIL_ADDRESS: str = ""       # Your Gmail address
    GMAIL_APP_PASSWORD: str = ""  # 16-char App Password from myaccount.google.com/apppasswords

    @property
    def supported_formats_list(self) -> list[str]:
        return [f.strip() for f in self.SUPPORTED_FORMATS.split(",")]

    @property
    def max_resume_bytes(self) -> int:
        return self.MAX_RESUME_SIZE_MB * 1024 * 1024

    @property
    def chroma_path(self) -> Path:
        return Path(self.CHROMA_PERSIST_DIR)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
