"""
InterviewAgent — question generation + transcript scoring.

Two public methods:
  generate_questions(jd_text, role, n) → list[QuestionItem]
  score_transcript(transcript, questions_config) → list[QuestionScore]

LLM chain: Sarvam AI → Ollama → deterministic fallback.
"""

import json
import re
import os
import asyncio
from typing import TypedDict
from loguru import logger
from app.core.config import get_settings


class QuestionItem(TypedDict):
    question: str
    expected_answer: str
    key_points: list[str]


class QuestionScore(TypedDict):
    score: int                   # 0-10
    feedback: str
    key_points_hit: list[str]
    key_points_missed: list[str]


class InterviewAgent:
    """Singleton-friendly agent for interview question generation and scoring."""

    # ── Question Generation ────────────────────────────────────────────────

    async def generate_questions(
        self, jd_text: str, role: str, n: int = 8, provider: str = "auto"
    ) -> list[QuestionItem]:
        """
        Generate n interview questions from a job description.
        provider: "auto" (Sarvam→Ollama), "sarvam" (Sarvam only→fallback), "ollama" (Ollama only→fallback)
        """
        prompt = self._build_generation_prompt(jd_text, role, n)

        if provider in ("auto", "sarvam"):
            result = await self._try_sarvam(prompt, max_tokens=2000)
            if result:
                parsed = self._parse_question_list(result, n)
                if parsed:
                    logger.info(f"Generated {len(parsed)} questions via Sarvam AI")
                    return parsed

        if provider in ("auto", "ollama"):
            result = await self._try_ollama(prompt, max_tokens=2000)
            if result:
                parsed = self._parse_question_list(result, n)
                if parsed:
                    logger.info(f"Generated {len(parsed)} questions via Ollama")
                    return parsed

        logger.info("Using fallback interview questions")
        return self._fallback_questions(role, n)

    def _build_generation_prompt(self, jd_text: str, role: str, n: int) -> str:
        return f"""You are an experienced recruiter. Generate exactly {n} structured interview questions for the following position.

Role: {role}

Job Description:
{jd_text[:3000]}

Create a balanced mix:
- 2 behavioral questions (STAR method)
- 2 technical/domain-specific questions
- 2 situational/problem-solving questions
- 1 motivation/culture-fit question
- 1 closing question

For EACH question, also provide:
- expected_answer: A brief description of what a strong answer should cover (2-3 sentences).
- key_points: A list of 2-4 specific keywords or concepts that a strong answer should mention.

Return ONLY a valid JSON array. No explanation, no markdown, no numbering.
Format:
[
  {{
    "question": "Tell me about...",
    "expected_answer": "The candidate should mention X, Y, and demonstrate Z.",
    "key_points": ["keyword1", "keyword2", "keyword3"]
  }}
]"""

    def _parse_question_list(self, text: str, min_count: int = 4) -> list[QuestionItem] | None:
        """Extract and validate a JSON array of QuestionItems from LLM output."""
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if not match:
            return None
        try:
            items = json.loads(match.group())
            if not isinstance(items, list) or len(items) < min_count:
                return None
            result = []
            for item in items:
                if isinstance(item, str):
                    # Old-format plain string — wrap it
                    result.append(QuestionItem(question=item, expected_answer="", key_points=[]))
                elif isinstance(item, dict) and "question" in item:
                    result.append(QuestionItem(
                        question=item.get("question", ""),
                        expected_answer=item.get("expected_answer", ""),
                        key_points=item.get("key_points", []),
                    ))
            return result if len(result) >= min_count else None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _fallback_questions(self, role: str, n: int) -> list[QuestionItem]:
        base = [
            QuestionItem(
                question=f"Tell me about your background and why you're interested in this {role} position.",
                expected_answer="Candidate should give a concise career summary, mention relevant experience, and show genuine interest in the role.",
                key_points=["relevant experience", "motivation", "career goals"],
            ),
            QuestionItem(
                question="Describe a challenging project you worked on and how you navigated it.",
                expected_answer="Should follow STAR method: situation, task, action, result. Should highlight problem-solving skills.",
                key_points=["STAR method", "problem-solving", "outcome", "teamwork"],
            ),
            QuestionItem(
                question=f"What are your strongest technical skills relevant to {role}?",
                expected_answer="Should list specific technologies/tools and give examples of applying them in real projects.",
                key_points=["specific tools", "practical examples", "depth of knowledge"],
            ),
            QuestionItem(
                question="Walk me through a situation where you had to meet a tight deadline.",
                expected_answer="Should demonstrate time management, prioritization, and composure under pressure.",
                key_points=["prioritization", "time management", "delivery", "pressure"],
            ),
            QuestionItem(
                question="Tell me about a time you worked in a team and had to resolve a disagreement.",
                expected_answer="Should show communication skills, empathy, and ability to find consensus.",
                key_points=["communication", "empathy", "consensus", "conflict resolution"],
            ),
            QuestionItem(
                question="How do you stay updated with new developments in your field?",
                expected_answer="Should mention specific sources: blogs, courses, conferences, communities, or open source.",
                key_points=["continuous learning", "specific resources", "curiosity"],
            ),
            QuestionItem(
                question="What is your approach to debugging or solving complex problems?",
                expected_answer="Should describe a systematic method: reproduce, isolate, hypothesize, test, document.",
                key_points=["systematic approach", "debugging tools", "root cause", "documentation"],
            ),
            QuestionItem(
                question=f"Where do you see yourself in 3–5 years, and how does this {role} role fit your goals?",
                expected_answer="Should show ambition aligned with the role. Honest about growth areas.",
                key_points=["career goals", "alignment with role", "growth mindset"],
            ),
        ]
        return base[:n]

    # ── Transcript Scoring ────────────────────────────────────────────────

    async def score_transcript(
        self,
        transcript: list[dict],          # [{question, answer}]
        questions_config: list[dict],     # [{question, expected_answer, key_points}]
        jd_text: str = "",               # Full job description for context
        role: str = "",                  # Role title
        provider: str = "auto",          # "auto" | "sarvam" | "ollama"
    ) -> list[QuestionScore]:
        """
        Score each answer against:
        1. The recruiter's expected answer + key points (if set)
        2. The job description (for relevance to the role)
        provider: "auto" (Sarvam→Ollama), "sarvam" (Sarvam only→fallback), "ollama" (Ollama only→fallback)
        Falls back to JD keyword overlap — never pure word count.
        """
        if not transcript:
            return []

        prompt = self._build_scoring_prompt(transcript, questions_config, jd_text, role)

        if provider in ("auto", "sarvam"):
            result = await self._try_sarvam(prompt, max_tokens=2000)
            if result:
                parsed = self._parse_score_list(result, len(transcript))
                if parsed:
                    logger.info(f"Scored {len(parsed)} answers via Sarvam AI")
                    return parsed

        if provider in ("auto", "ollama"):
            result = await self._try_ollama(prompt, max_tokens=2000)
            if result:
                parsed = self._parse_score_list(result, len(transcript))
                if parsed:
                    logger.info(f"Scored {len(parsed)} answers via Ollama")
                    return parsed

        logger.info("Using content-relevance fallback scoring")
        return self._fallback_score(transcript, questions_config, jd_text)

    def _build_scoring_prompt(
        self,
        transcript: list[dict],
        questions_config: list[dict],
        jd_text: str = "",
        role: str = "",
    ) -> str:
        jd_section = ""
        if jd_text:
            jd_section = f"""
Job Description (use this to judge relevance of answers to the role):
---
{jd_text[:2000]}
---
"""
        role_line = f"Role: {role}\n" if role else ""

        qa_pairs = []
        for i, item in enumerate(transcript):
            cfg = questions_config[i] if i < len(questions_config) else {}
            expected = cfg.get("expected_answer", "")
            key_pts = cfg.get("key_points") or []
            expected_section = f"Expected answer: {expected}" if expected else "Expected answer: (evaluate based on the question and job description)"
            kp_section = f"Key concepts to check: {', '.join(key_pts)}" if key_pts else "Key concepts: (infer from question and JD)"
            qa_pairs.append(
                f"Q{i+1}: {item.get('question', '')}\n"
                f"{expected_section}\n"
                f"{kp_section}\n"
                f"Candidate's answer: {item.get('answer', '(no answer given)')}"
            )

        pairs_text = "\n\n".join(qa_pairs)
        n = len(transcript)

        return f"""You are a senior hiring manager evaluating interview answers for a {role or "professional"} role.
{role_line}{jd_section}
CRITICAL EVALUATION RULES:
- Score based on CONTENT QUALITY and RELEVANCE to the question and role — NOT answer length
- A short, precise answer can score higher than a long, vague one
- Severely penalise off-topic, irrelevant, nonsensical, or clearly made-up answers
- An answer that doesn't address the question at all scores 0-2
- An answer that is somewhat relevant but lacks depth scores 3-5
- A strong, role-relevant answer with concrete examples scores 7-9
- An exceptional answer with depth, specifics, and role alignment scores 9-10

Scoring rubric (0-10):
- 9-10: Excellent — directly addresses the question, relevant to role, concrete examples, depth
- 7-8: Good — solid answer, relevant, covers key aspects, minor gaps
- 5-6: Adequate — partially addresses the question, some relevant content but vague
- 3-4: Weak — mostly off-topic, vague, or generic platitudes with no substance
- 0-2: Poor — irrelevant, nonsensical, very short non-answer, or clearly fabricated

For each Q&A pair below, evaluate strictly against the above rubric.
List which key concepts were mentioned (key_points_hit) and which were missing or inadequately covered (key_points_missed).

{pairs_text}

Return ONLY a valid JSON array with exactly {n} objects. No explanation, no markdown, no preamble.
[
  {{
    "score": 7,
    "feedback": "Specific, actionable feedback on what was good and what was missing.",
    "key_points_hit": ["concept1", "concept2"],
    "key_points_missed": ["concept3"]
  }}
]"""

    def _parse_score_list(self, text: str, expected_count: int) -> list[QuestionScore] | None:
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if not match:
            return None
        try:
            items = json.loads(match.group())
            if not isinstance(items, list) or len(items) < max(1, expected_count - 1):
                return None
            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                result.append(QuestionScore(
                    score=max(0, min(10, int(item.get("score", 5)))),
                    feedback=str(item.get("feedback", "")),
                    key_points_hit=list(item.get("key_points_hit", [])),
                    key_points_missed=list(item.get("key_points_missed", [])),
                ))
            return result if result else None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _fallback_score(
        self,
        transcript: list[dict],
        questions_config: list[dict],
        jd_text: str = "",
    ) -> list[QuestionScore]:
        """
        Content-relevance fallback when LLM is unavailable.
        Uses keyword overlap against: key_points > expected_answer > JD text.
        Never uses pure word count as a score signal.
        """
        # Build a bag-of-words from the JD for relevance checking
        jd_words: set[str] = set()
        if jd_text:
            jd_words = {w.lower() for w in jd_text.split() if len(w) > 3}

        scores = []
        for i, item in enumerate(transcript):
            answer = item.get("answer", "").lower()
            answer_words = set(answer.split())
            cfg = questions_config[i] if i < len(questions_config) else {}
            key_points = [kp.lower() for kp in (cfg.get("key_points") or [])]
            expected = (cfg.get("expected_answer") or "").lower()

            # Build the reference vocabulary to match against
            ref_vocab: list[str] = []
            if key_points:
                ref_vocab = key_points
            elif expected:
                # Extract meaningful words from expected answer
                ref_vocab = [w for w in expected.split() if len(w) > 3][:20]
            elif jd_words:
                # Extract meaningful words from JD — common role keywords
                ref_vocab = [w for w in jd_words if len(w) > 4][:30]

            hit = [kp for kp in ref_vocab if kp in answer]
            missed = [kp for kp in ref_vocab if kp not in answer]

            if ref_vocab:
                coverage = len(hit) / len(ref_vocab)
                # Check answer is non-trivial (at least 10 words)
                word_count = len(answer.split())
                if word_count < 5:
                    raw = coverage * 3  # very short = likely poor
                elif word_count < 15:
                    raw = coverage * 5 + 1
                else:
                    raw = coverage * 7 + 2  # some base for a real answer
                score = max(0, min(10, round(raw)))
                feedback = f"{len(hit)}/{len(ref_vocab)} relevant concepts mentioned."
            else:
                # No reference vocabulary — at least check answer isn't empty
                word_count = len(answer.split())
                score = 3 if word_count >= 20 else (1 if word_count > 0 else 0)
                feedback = "Unable to evaluate without job description or expected answer."
                hit, missed = [], []

            scores.append(QuestionScore(
                score=score,
                feedback=feedback,
                key_points_hit=hit[:10],
                key_points_missed=missed[:10],
            ))
        return scores

    # ── LLM helpers ────────────────────────────────────────────────────────

    async def _try_sarvam(self, prompt: str, max_tokens: int = 1200) -> str | None:
        sarvam_key = get_settings().SARVAM_API_KEY
        if not sarvam_key:
            return None
        try:
            import aiohttp
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    "https://api.sarvam.ai/v1/chat/completions",
                    headers={"api-subscription-key": sarvam_key, "Content-Type": "application/json"},
                    json={
                        "model": "sarvam-m",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                    },
                    timeout=aiohttp.ClientTimeout(total=40),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"]
                        # Strip <think>...</think> reasoning blocks emitted by sarvam-m
                        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
                        return content
        except Exception as e:
            logger.debug(f"Sarvam call failed: {e}")
        return None

    async def _try_ollama(self, prompt: str, max_tokens: int = 1200) -> str | None:
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct-q4_K_M")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"{ollama_url}/api/generate",
                    json={"model": ollama_model, "prompt": prompt, "stream": False},
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("response", "")
        except Exception as e:
            logger.debug(f"Ollama call failed: {e}")
        return None
