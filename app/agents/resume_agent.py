"""
ResumeAgent — thin orchestration layer around parse/embed/match services.

Provides a stable interface so routes don't import individual services directly.
"""

from loguru import logger


class ResumeAgent:
    """
    Wraps the resume parsing, embedding, and matching pipeline.
    Instantiated once in main.py and injected into routes via set_services().
    """

    def __init__(self, embedding_service, vector_store, matching_engine):
        self._embedding = embedding_service
        self._vector_store = vector_store
        self._matching_engine = matching_engine

    async def parse_and_embed(self, file_bytes: bytes, filename: str) -> dict:
        """
        Parse a resume file and store its embedding in the vector store.
        Returns parsed resume metadata dict (name, email, skills, ...).
        """
        from app.services.resume_parser import parse_resume
        parsed = parse_resume(file_bytes, filename)

        text = parsed.get("raw_text", "") or parsed.get("text", "")
        if text:
            embedding = self._embedding.encode(text)
            resume_id = parsed.get("resume_id") or parsed.get("id", "")
            if resume_id:
                self._vector_store.add(resume_id, embedding, metadata=parsed)
                logger.debug(f"ResumeAgent: embedded resume {resume_id}")

        return parsed

    async def match_jd(self, jd_text: str, session_id: str, top_k: int = 10) -> list[dict]:
        """
        Match a job description against all stored resumes.
        Returns ranked list of candidate matches.
        """
        results = self._matching_engine.match(jd_text, top_k=top_k)
        logger.debug(f"ResumeAgent: matched JD for session {session_id} → {len(results)} results")
        return results
