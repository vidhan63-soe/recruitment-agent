"""
Sarvam AI Scorer Service.
Uses Sarvam AI's chat completion API (sarvam-m model) for candidate evaluation.
OpenAI-compatible endpoint — much cheaper than GPT-4, good for Indian market MVP.

API: POST https://api.sarvam.ai/v1/chat/completions
Auth: api-subscription-key header
Model: sarvam-m (24B params, multilingual)

Free tier: Rs.1000 credits on signup
Rate limit: 60 req/min
"""

import json
import re
import httpx
from loguru import logger


class SarvamScorer:
    """Scores candidates using Sarvam AI's sarvam-m model."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.sarvam.ai/v1"
        self.model = "sarvam-m"
        self.available = False

    async def check_health(self) -> bool:
        """Verify API key works with a tiny request."""
        if not self.api_key or self.api_key == "your-sarvam-api-key-here":
            logger.warning("Sarvam AI API key not configured")
            self.available = False
            return False

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "api-subscription-key": self.api_key,
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "Reply with just: ok"}],
                        "max_tokens": 5,
                        "temperature": 0.1,
                    },
                )
                if resp.status_code == 200:
                    self.available = True
                    logger.info("Sarvam AI connected: sarvam-m model ready")
                    return True
                else:
                    logger.warning(
                        f"Sarvam AI returned {resp.status_code}: {resp.text[:200]}"
                    )
                    self.available = False
                    return False

        except Exception as e:
            logger.warning(f"Sarvam AI not reachable: {e}")
            self.available = False
            return False

    async def score_candidate(
        self,
        jd_text: str,
        resume_chunks: list[dict],
        candidate_name: str,
    ) -> dict:
        """
        Use Sarvam AI to evaluate candidate-JD fit.
        Returns score (0-1), matched_skills, missing_skills, summary.
        """
        if not self.available:
            return self._fallback_score(jd_text, resume_chunks)

        resume_context = "\n---\n".join(
            [c["text"] for c in resume_chunks[:3]]
        )

        prompt = f"""You are an expert technical recruiter evaluating candidates. 
Analyze how well this candidate matches the job description.

JOB DESCRIPTION:
{jd_text[:1500]}

CANDIDATE RESUME EXCERPTS ({candidate_name}):
{resume_context[:2000]}

You MUST respond with ONLY this JSON format, nothing else:
{{
    "score": <float 0.0 to 1.0>,
    "matched_skills": ["skill1", "skill2"],
    "missing_skills": ["skill1", "skill2"],
    "summary": "2-3 sentence evaluation"
}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "api-subscription-key": self.api_key,
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a technical recruiter AI. Always respond with valid JSON only.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 500,
                        "temperature": 0.1,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return self._parse_response(content)

                elif resp.status_code == 429:
                    logger.warning("Sarvam AI rate limited — using fallback")
                    return self._fallback_score(jd_text, resume_chunks)

                else:
                    logger.error(f"Sarvam AI error {resp.status_code}: {resp.text[:200]}")

        except Exception as e:
            logger.error(f"Sarvam AI scoring failed for {candidate_name}: {e}")

        return self._fallback_score(jd_text, resume_chunks)

    def _parse_response(self, text: str) -> dict:
        """Extract structured data from LLM response."""
        try:
            # Strip thinking tags if present (sarvam-m hybrid mode)
            if "</think>" in text:
                text = text.split("</think>")[-1].strip()

            # Find JSON in response
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
            logger.warning(f"Failed to parse Sarvam response: {e}")

        return {"llm_score": 0.5, "matched_skills": [], "missing_skills": [], "summary": ""}

    def _fallback_score(self, jd_text: str, resume_chunks: list[dict]) -> dict:
        """Keyword-based scoring when API is unavailable."""
        jd_words = set(
            word.lower()
            for word in re.findall(r"\b[a-zA-Z+#]{2,}\b", jd_text)
        )

        tech_keywords = {
            "python", "java", "javascript", "typescript", "react", "angular",
            "vue", "node", "django", "flask", "fastapi", "spring", "sql",
            "nosql", "mongodb", "postgresql", "mysql", "redis", "docker",
            "kubernetes", "aws", "azure", "gcp", "git", "ci/cd", "agile",
            "scrum", "machine learning", "deep learning", "nlp", "pytorch",
            "tensorflow", "pandas", "numpy", "c++", "rust", "go", "scala",
        }

        jd_skills = jd_words & tech_keywords
        resume_text = " ".join(c["text"].lower() for c in resume_chunks)
        resume_words = set(re.findall(r"\b[a-zA-Z+#]{2,}\b", resume_text))

        matched = list(jd_skills & resume_words)
        missing = list(jd_skills - resume_words)

        score = len(matched) / len(jd_skills) if jd_skills else 0.5

        return {
            "llm_score": round(score, 3),
            "matched_skills": matched[:10],
            "missing_skills": missing[:10],
            "summary": f"Keyword match: {len(matched)}/{len(jd_skills)} skills (fallback — Sarvam AI unavailable)",
        }
