"""
LLM Scorer Service.
Uses local Ollama instance to evaluate candidate-JD fit.
Falls back to rule-based scoring if Ollama is unavailable.

GPU budget:
  - Embedding model: ~400MB-1.2GB VRAM
  - Ollama LLM: ~2.5-4GB VRAM
  - Total on 1650Ti: embedding(400MB) + phi3:mini(2.5GB) = ~2.9GB / 4GB ✓
  - Total on 3050: embedding(1.2GB) + mistral-7b-q4(4GB) = ~5.2GB / 6GB ✓
"""

import json
import re
import httpx
from loguru import logger


class LLMScorer:
    """Scores candidates using local Ollama LLM."""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.available = False

    async def check_health(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = [m["name"] for m in models]
                    self.available = any(self.model in name for name in model_names)
                    if self.available:
                        logger.info(f"Ollama connected: model '{self.model}' ready")
                    else:
                        logger.warning(
                            f"Ollama running but model '{self.model}' not found. "
                            f"Available: {model_names}. "
                            f"Run: ollama pull {self.model}"
                        )
                    return self.available
        except Exception as e:
            logger.warning(f"Ollama not reachable at {self.base_url}: {e}")
            self.available = False
            return False

    async def score_candidate(
        self,
        jd_text: str,
        resume_chunks: list[dict],
        candidate_name: str,
    ) -> dict:
        """
        Use LLM to evaluate how well a candidate matches the JD.
        Returns score (0-1), matched_skills, missing_skills, summary.
        """
        if not self.available:
            return self._fallback_score(jd_text, resume_chunks)

        # Build context from top chunks
        resume_context = "\n---\n".join(
            [c["text"] for c in resume_chunks[:3]]
        )

        prompt = f"""You are an expert technical recruiter. Evaluate how well this candidate matches the job description.

JOB DESCRIPTION:
{jd_text[:1500]}

CANDIDATE RESUME EXCERPTS ({candidate_name}):
{resume_context[:2000]}

Respond in this exact JSON format only, no other text:
{{
    "score": 0.0 to 1.0,
    "matched_skills": ["skill1", "skill2"],
    "missing_skills": ["skill1", "skill2"],
    "summary": "2-3 sentence evaluation"
}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 500,
                        },
                    },
                )

                if resp.status_code == 200:
                    response_text = resp.json().get("response", "")
                    return self._parse_llm_response(response_text)

        except Exception as e:
            logger.error(f"LLM scoring failed for {candidate_name}: {e}")

        return self._fallback_score(jd_text, resume_chunks)

    def _parse_llm_response(self, text: str) -> dict:
        """Extract structured data from LLM response."""
        try:
            # Try to find JSON in the response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "llm_score": max(0.0, min(1.0, float(data.get("score", 0.5)))),
                    "matched_skills": data.get("matched_skills", []),
                    "missing_skills": data.get("missing_skills", []),
                    "summary": data.get("summary", ""),
                }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")

        return {"llm_score": 0.5, "matched_skills": [], "missing_skills": [], "summary": ""}

    def _fallback_score(self, jd_text: str, resume_chunks: list[dict]) -> dict:
        """
        Rule-based scoring when Ollama is unavailable.
        Uses keyword overlap as a proxy.
        """
        # Extract keywords from JD
        jd_words = set(
            word.lower()
            for word in re.findall(r"\b[a-zA-Z+#]{2,}\b", jd_text)
        )

        # Common tech keywords to look for
        tech_keywords = {
            "python", "java", "javascript", "typescript", "react", "angular",
            "vue", "node", "django", "flask", "fastapi", "spring", "sql",
            "nosql", "mongodb", "postgresql", "mysql", "redis", "docker",
            "kubernetes", "aws", "azure", "gcp", "git", "ci/cd", "agile",
            "scrum", "machine learning", "deep learning", "nlp", "pytorch",
            "tensorflow", "pandas", "numpy", "c++", "rust", "go", "scala",
        }

        jd_skills = jd_words & tech_keywords

        # Check resume chunks for matches
        resume_text = " ".join(c["text"].lower() for c in resume_chunks)
        resume_words = set(re.findall(r"\b[a-zA-Z+#]{2,}\b", resume_text))

        matched = list(jd_skills & resume_words)
        missing = list(jd_skills - resume_words)

        if jd_skills:
            score = len(matched) / len(jd_skills)
        else:
            score = 0.5

        return {
            "llm_score": round(score, 3),
            "matched_skills": matched[:10],
            "missing_skills": missing[:10],
            "summary": f"Keyword match: {len(matched)}/{len(jd_skills)} required skills found (fallback scoring — Ollama unavailable)",
        }
