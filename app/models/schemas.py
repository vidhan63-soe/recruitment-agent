"""
Data models for the recruitment pipeline.
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Resume Models ──────────────────────────────

class ResumeChunk(BaseModel):
    chunk_id: str
    resume_id: str
    text: str
    chunk_index: int
    metadata: dict = Field(default_factory=dict)


class ParsedResume(BaseModel):
    resume_id: str
    filename: str
    candidate_name: str = "Unknown"
    email: str = ""
    phone: str = ""
    raw_text: str
    sections: dict = Field(default_factory=dict)  # education, experience, skills, etc.
    chunks: list[ResumeChunk] = Field(default_factory=list)
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


# ── Job Description Models ─────────────────────

class JobDescription(BaseModel):
    jd_id: str
    title: str
    company: str = ""
    raw_text: str
    required_skills: list[str] = Field(default_factory=list)
    experience_years: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Matching Models ────────────────────────────

class CandidateScore(BaseModel):
    resume_id: str
    candidate_name: str
    email: str
    filename: str
    semantic_score: float = Field(ge=0.0, le=1.0, description="RAG similarity score")
    llm_score: float = Field(ge=0.0, le=1.0, description="LLM evaluation score")
    final_score: float = Field(ge=0.0, le=1.0, description="Weighted combined score")
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    summary: str = ""
    rank: int = 0


class MatchResult(BaseModel):
    jd_id: str
    jd_title: str
    total_resumes: int
    candidates: list[CandidateScore]
    processed_at: datetime = Field(default_factory=datetime.utcnow)


# ── API Models ─────────────────────────────────

class UploadResponse(BaseModel):
    resume_id: str
    filename: str
    candidate_name: str
    status: str = "processed"
    chunk_count: int = 0


class MatchRequest(BaseModel):
    jd_text: str
    jd_title: str = "Untitled Position"
    company: str = ""
    top_k: int = 10
    min_score: float = 0.35


class HealthResponse(BaseModel):
    status: str
    gpu: str
    embedding_model: str
    llm_model: str
    total_resumes: int
    version: str = "0.1.0-mvp"
