"""
SCORING ENGINE
===============
Generates a comprehensive interview scorecard and report.

Evaluation Dimensions:
  1. Communication (clarity, structure, articulation)
  2. Confidence (voice analysis, hesitation, filler words)
  3. Domain Knowledge (technical accuracy, depth)
  4. Behavioral Competency (STAR method, real examples)
  5. Problem Solving (approach, creativity, structure)
  6. Cultural Fit (enthusiasm, questions, values alignment)
  7. Integrity (consistency, cheating flags)
"""

import time
from typing import Optional


class ScoringEngine:
    """Generates the final interview evaluation report."""

    def generate_report(
        self,
        interview_engine,
        confidence_analyzer,
        cheating_detector,
    ) -> dict:
        """
        Compile all data into a comprehensive interview report.
        """
        transcript = interview_engine.get_transcript()
        confidence = confidence_analyzer.get_summary()
        cheating   = cheating_detector.get_detailed_report()

        if not transcript:
            return {"error": "No interview data available"}

        # ── Calculate dimension scores ──
        communication_score = self._score_communication(transcript, confidence)
        confidence_score    = self._score_confidence(confidence)
        knowledge_score     = self._score_knowledge(transcript)
        behavioral_score    = self._score_behavioral(transcript)
        problem_solving     = self._score_problem_solving(transcript)
        cultural_fit        = self._score_cultural_fit(transcript)
        integrity_score     = self._score_integrity(cheating, transcript)

        dimensions = {
            "communication": {
                "score": communication_score,
                "max": 10,
                "weight": 0.15,
                "feedback": self._communication_feedback(communication_score, confidence),
            },
            "confidence": {
                "score": confidence_score,
                "max": 10,
                "weight": 0.10,
                "feedback": self._confidence_feedback(confidence_score, confidence),
            },
            "domain_knowledge": {
                "score": knowledge_score,
                "max": 10,
                "weight": 0.25,
                "feedback": self._knowledge_feedback(knowledge_score, transcript),
            },
            "behavioral_competency": {
                "score": behavioral_score,
                "max": 10,
                "weight": 0.20,
                "feedback": self._behavioral_feedback(behavioral_score),
            },
            "problem_solving": {
                "score": problem_solving,
                "max": 10,
                "weight": 0.15,
                "feedback": self._problem_solving_feedback(problem_solving),
            },
            "cultural_fit": {
                "score": cultural_fit,
                "max": 10,
                "weight": 0.10,
                "feedback": self._cultural_feedback(cultural_fit),
            },
            "integrity": {
                "score": integrity_score,
                "max": 10,
                "weight": 0.05,
                "feedback": self._integrity_feedback(integrity_score, cheating),
            },
        }

        # ── Weighted overall score ──
        overall = sum(
            d["score"] * d["weight"] for d in dimensions.values()
        )

        # ── Recommendation ──
        if overall >= 8.0 and integrity_score >= 7:
            recommendation = "Strong Hire"
        elif overall >= 6.5 and integrity_score >= 6:
            recommendation = "Hire"
        elif overall >= 5.0:
            recommendation = "Maybe — Needs Further Evaluation"
        else:
            recommendation = "No Hire"

        if integrity_score < 4:
            recommendation = "No Hire — Integrity Concerns"

        # ── Per-question breakdown ──
        question_analysis = []
        for t in transcript:
            qa = {
                "question": t.get("question", ""),
                "answer_preview": t["candidate"][:200],
                "phase": t.get("state", ""),
                "difficulty": t.get("difficulty", "medium"),
            }
            question_analysis.append(qa)

        # ── Build report ──
        elapsed = time.time() - interview_engine.start_time if interview_engine.start_time else 0

        report = {
            "summary": {
                "candidate_name": interview_engine.config.candidate_name,
                "role": interview_engine.config.role,
                "experience_level": interview_engine.config.experience_level,
                "domain": interview_engine.config.domain,
                "date": time.strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": round(elapsed / 60, 1),
                "questions_asked": len(transcript),
                "overall_score": round(overall, 1),
                "recommendation": recommendation,
            },
            "dimensions": dimensions,
            "confidence_analysis": confidence,
            "cheating_assessment": cheating["summary"],
            "question_breakdown": question_analysis,
            "strengths": self._identify_strengths(dimensions),
            "areas_for_improvement": self._identify_weaknesses(dimensions),
            "detailed_feedback": self._generate_detailed_feedback(
                dimensions, confidence, cheating["summary"]
            ),
        }

        return report

    # ── Scoring methods ──

    def _score_communication(self, transcript: list, confidence: dict) -> float:
        """Score based on clarity, structure, and articulation."""
        if not transcript:
            return 0

        scores = []
        for t in transcript:
            text = t["candidate"]
            words = text.split()
            score = 5.0

            # Length appropriateness
            if 20 <= len(words) <= 150:
                score += 1.0
            elif len(words) < 10:
                score -= 2.0

            # Sentence structure (has multiple sentences)
            sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
            if len(sentences) >= 2:
                score += 0.5

            # Uses specific examples
            specifics = ["for example", "specifically", "such as", "in particular",
                         "when i", "during my", "at my previous"]
            if any(s in text.lower() for s in specifics):
                score += 1.0

            scores.append(min(10, max(0, score)))

        # Factor in filler percentage
        filler_pct = confidence.get("filler_percentage", 0)
        filler_penalty = min(2, filler_pct / 5)

        return round(sum(scores) / len(scores) - filler_penalty, 1)

    def _score_confidence(self, confidence: dict) -> float:
        return confidence.get("overall_score", 5.0)

    def _score_knowledge(self, transcript: list) -> float:
        """Score domain knowledge depth."""
        if not transcript:
            return 0

        scores = []
        for t in transcript:
            text = t["candidate"]
            score = 5.0

            words = text.split()
            # Detail level
            if len(words) > 40:
                score += 1.0
            if len(words) > 80:
                score += 0.5

            # Specificity indicators
            if any(c.isdigit() for c in text):
                score += 0.5  # Uses specific numbers
            if any(w in text.lower() for w in ["percent", "million", "metric", "kpi"]):
                score += 0.5

            scores.append(min(10, max(0, score)))

        return round(sum(scores) / len(scores), 1)

    def _score_behavioral(self, transcript: list) -> float:
        """Score behavioral competency (STAR method usage)."""
        if not transcript:
            return 0

        behavioral_qs = [t for t in transcript if t.get("state") in ("behavioral", "followup")]
        if not behavioral_qs:
            return 5.0

        scores = []
        for t in behavioral_qs:
            text = t["candidate"].lower()
            score = 4.0

            # STAR components
            star = {
                "situation": ["situation", "context", "background", "when i was"],
                "task": ["task", "responsible", "my role", "i needed to", "objective"],
                "action": ["i did", "i decided", "i took", "my approach", "i implemented"],
                "result": ["result", "outcome", "achieved", "improved", "led to", "learned"],
            }

            for component, keywords in star.items():
                if any(kw in text for kw in keywords):
                    score += 1.5

            scores.append(min(10, max(0, score)))

        return round(sum(scores) / len(scores), 1)

    def _score_problem_solving(self, transcript: list) -> float:
        """Score problem-solving approach."""
        if not transcript:
            return 0

        scenario_qs = [t for t in transcript if t.get("state") == "scenario"]
        if not scenario_qs:
            return 5.0

        scores = []
        for t in scenario_qs:
            text = t["candidate"].lower()
            score = 4.0

            # Structured thinking indicators
            structure = ["first", "then", "next", "finally", "step", "approach",
                         "analyze", "evaluate", "consider", "prioritize"]
            hits = sum(1 for s in structure if s in text)
            score += min(hits * 0.5, 3.0)

            # Creativity indicators
            creative = ["alternative", "innovative", "different angle", "creative",
                        "what if", "another option"]
            if any(c in text for c in creative):
                score += 1.0

            scores.append(min(10, max(0, score)))

        return round(sum(scores) / len(scores), 1)

    def _score_cultural_fit(self, transcript: list) -> float:
        """Score cultural fit and enthusiasm."""
        if not transcript:
            return 5.0

        score = 5.0
        all_text = " ".join(t["candidate"] for t in transcript).lower()

        # Enthusiasm indicators
        positive = ["excited", "passionate", "love", "enjoy", "thrilled",
                     "eager", "looking forward", "great opportunity"]
        pos_count = sum(1 for p in positive if p in all_text)
        score += min(pos_count * 0.5, 2.0)

        # Team orientation
        team = ["team", "collaborate", "together", "we", "our"]
        team_count = sum(1 for t in team if t in all_text)
        score += min(team_count * 0.3, 1.5)

        # Growth mindset
        growth = ["learn", "grow", "improve", "develop", "challenge"]
        growth_count = sum(1 for g in growth if g in all_text)
        score += min(growth_count * 0.3, 1.0)

        return round(min(10, max(0, score)), 1)

    def _score_integrity(self, cheating: dict, transcript: list) -> float:
        """Score integrity based on cheating detection."""
        severity = cheating.get("summary", {}).get("severity_score", 0)

        if severity == 0:
            return 10.0
        elif severity < 5:
            return 8.0
        elif severity < 15:
            return 6.0
        elif severity < 30:
            return 4.0
        else:
            return 2.0

    # ── Feedback generators ──

    def _communication_feedback(self, score, confidence):
        if score >= 8:
            return "Excellent communicator. Clear, structured, and articulate responses."
        elif score >= 6:
            return "Good communication skills. Could improve on reducing filler words and being more concise."
        elif score >= 4:
            return "Average communication. Responses need more structure and clarity."
        else:
            return "Communication needs significant improvement. Responses were unclear or too brief."

    def _confidence_feedback(self, score, confidence):
        filler_pct = confidence.get("filler_percentage", 0)
        trend = confidence.get("trend", "stable")
        parts = []
        if score >= 7:
            parts.append("Confident and composed throughout.")
        elif score >= 5:
            parts.append("Moderately confident.")
        else:
            parts.append("Showed signs of nervousness.")
        if filler_pct > 5:
            parts.append(f"High filler word usage ({filler_pct}%).")
        if trend == "improving":
            parts.append("Confidence improved as the interview progressed.")
        elif trend == "declining":
            parts.append("Confidence appeared to decline over time.")
        return " ".join(parts)

    def _knowledge_feedback(self, score, transcript):
        if score >= 8:
            return "Strong domain expertise demonstrated with specific examples and depth."
        elif score >= 6:
            return "Adequate domain knowledge. Some areas could use more depth."
        else:
            return "Domain knowledge appears limited. Answers lacked technical specificity."

    def _behavioral_feedback(self, score):
        if score >= 7:
            return "Excellent use of specific examples and STAR method in behavioral answers."
        elif score >= 5:
            return "Provided some examples but could benefit from more structured storytelling."
        else:
            return "Behavioral answers were vague. Needs concrete examples using the STAR framework."

    def _problem_solving_feedback(self, score):
        if score >= 7:
            return "Demonstrated structured, creative problem-solving approach."
        elif score >= 5:
            return "Showed adequate problem-solving skills. Could be more systematic."
        else:
            return "Problem-solving approach needs work. Consider frameworks for structured thinking."

    def _cultural_feedback(self, score):
        if score >= 7:
            return "Shows enthusiasm, team orientation, and growth mindset."
        elif score >= 5:
            return "Moderate cultural alignment. Could show more enthusiasm."
        else:
            return "Limited indicators of cultural fit. Didn't demonstrate passion for the role."

    def _integrity_feedback(self, score, cheating):
        risk = cheating.get("summary", {}).get("risk_level", "none")
        if risk == "none":
            return "No integrity concerns detected."
        elif risk == "low":
            return "Minor flags detected but likely inconsequential."
        elif risk == "medium":
            return "Several suspicious signals detected. Recommend verification."
        else:
            return "Significant integrity concerns. Multiple cheating indicators flagged."

    def _identify_strengths(self, dimensions: dict) -> list[str]:
        strengths = []
        for name, d in dimensions.items():
            if d["score"] >= 7:
                strengths.append(name.replace("_", " ").title())
        return strengths or ["No standout strengths identified"]

    def _identify_weaknesses(self, dimensions: dict) -> list[str]:
        weaknesses = []
        for name, d in dimensions.items():
            if d["score"] < 5:
                weaknesses.append(name.replace("_", " ").title())
        return weaknesses or ["No significant weaknesses"]

    def _generate_detailed_feedback(self, dimensions, confidence, cheating):
        """Generate a human-readable feedback summary."""
        overall = sum(d["score"] * d["weight"] for d in dimensions.values())

        parts = [f"Overall Performance: {overall:.1f}/10\n"]

        for name, d in sorted(dimensions.items(), key=lambda x: -x[1]["score"]):
            label = name.replace("_", " ").title()
            parts.append(f"  {label}: {d['score']}/10 — {d['feedback']}")

        if cheating.get("risk_level", "none") != "none":
            parts.append(f"\nIntegrity Alert: {cheating['risk_level']} risk level detected.")

        return "\n".join(parts)
