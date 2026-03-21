"""
INTERVIEW ENGINE — State Machine & Question Flow
==================================================
Manages the complete interview lifecycle:
  INTRO → BEHAVIORAL → DOMAIN → FOLLOWUP → SCENARIO → CLOSING → COMPLETE

Universal question framework works for ANY role — SDE, IBD, PM, Data Science,
Marketing, HR, Finance, etc. Questions adapt based on the role & domain.
"""

import time
import enum
import random
from dataclasses import dataclass, field
from typing import Optional


class InterviewState(enum.Enum):
    NOT_STARTED  = "not_started"
    INTRO        = "intro"           # Warm-up & background
    BEHAVIORAL   = "behavioral"      # STAR method questions
    DOMAIN       = "domain"          # Role-specific technical/domain
    FOLLOWUP     = "followup"        # Probing deeper on weak answers
    SCENARIO     = "scenario"        # Situational judgment
    CLOSING      = "closing"         # Candidate questions & wrap-up
    COMPLETE     = "complete"


@dataclass
class InterviewConfig:
    role: str = "Software Engineer"
    experience_level: str = "mid"     # junior, mid, senior, lead
    domain: str = "general"           # tech, finance, consulting, marketing, etc.
    candidate_name: str = "Candidate"
    language: str = "en"              # en, hi, etc.
    num_questions: int = 8
    difficulty: str = "adaptive"      # easy, medium, hard, adaptive

    def to_dict(self):
        return {
            "role": self.role,
            "experience_level": self.experience_level,
            "domain": self.domain,
            "candidate_name": self.candidate_name,
            "language": self.language,
            "num_questions": self.num_questions,
            "difficulty": self.difficulty,
        }


# ════════════════════════════════════════════════════
# Universal Question Bank
# ════════════════════════════════════════════════════
# These are TEMPLATES — the LLM will personalize them
# based on role/domain during the interview.

INTRO_QUESTIONS = [
    "Tell me about yourself and your background.",
    "What motivated you to apply for this role?",
    "Walk me through your career journey so far.",
]

BEHAVIORAL_QUESTIONS = [
    # Leadership & Initiative
    "Tell me about a time you took initiative on a project without being asked.",
    "Describe a situation where you had to lead a team through a difficult challenge.",
    # Conflict & Communication
    "Give me an example of a time you had a disagreement with a colleague. How did you handle it?",
    "Tell me about a time you had to deliver difficult feedback to someone.",
    # Problem Solving
    "Describe a complex problem you solved. What was your approach?",
    "Tell me about a time when you failed at something. What did you learn?",
    # Adaptability
    "Describe a situation where priorities changed suddenly. How did you adapt?",
    "Tell me about a time you had to learn something new quickly under pressure.",
    # Teamwork
    "Give me an example of a successful collaboration across teams or departments.",
    "Tell me about a time you helped a struggling team member.",
]

SCENARIO_QUESTIONS = [
    "If you were given a project with unclear requirements and a tight deadline, how would you approach it?",
    "Imagine you discover a critical issue right before a major delivery. What do you do?",
    "If you disagreed with your manager's decision on an important matter, how would you handle it?",
    "You're halfway through a project and realize the approach won't work. What's your next step?",
    "A key team member suddenly leaves mid-project. How do you handle the situation?",
]

CLOSING_PROMPTS = [
    "Do you have any questions about the role or the team?",
    "Is there anything else you'd like to share that we haven't covered?",
    "What are your expectations for this position?",
]


class InterviewEngine:
    """
    Drives the interview through phases, selects questions,
    and adapts difficulty based on candidate performance.
    """

    def __init__(self):
        self.config = InterviewConfig()
        self.state  = InterviewState.NOT_STARTED
        self.start_time: Optional[float] = None

        self.current_question_idx = 0
        self._current_question    = ""
        self._phase_questions: dict[str, list[str]] = {}
        self._phase_idx: dict[str, int] = {}

        self._transcript: list[dict] = []
        self._answer_quality: list[float] = []  # Running quality scores

        # Adaptive difficulty tracking
        self._consecutive_good = 0
        self._consecutive_weak = 0
        self._current_difficulty = "medium"

    def configure(self, config: InterviewConfig):
        """Set up a new interview session."""
        self.config = config
        self.state  = InterviewState.NOT_STARTED
        self.start_time = None
        self.current_question_idx = 0
        self._current_question = ""
        self._transcript = []
        self._answer_quality = []
        self._consecutive_good = 0
        self._consecutive_weak = 0
        self._current_difficulty = config.difficulty if config.difficulty != "adaptive" else "medium"

        # Prepare question pools for each phase
        self._phase_questions = {
            "intro":      random.sample(INTRO_QUESTIONS, min(2, len(INTRO_QUESTIONS))),
            "behavioral": random.sample(BEHAVIORAL_QUESTIONS, min(3, len(BEHAVIORAL_QUESTIONS))),
            "scenario":   random.sample(SCENARIO_QUESTIONS, min(2, len(SCENARIO_QUESTIONS))),
            "closing":    CLOSING_PROMPTS[:1],
        }
        self._phase_idx = {k: 0 for k in self._phase_questions}

        print(f"  [Interview] Configured: {config.role} ({config.experience_level})")
        print(f"  [Interview] Questions: {config.num_questions}, Difficulty: {config.difficulty}")

    def start(self):
        """Begin the interview."""
        if self.state == InterviewState.NOT_STARTED:
            self.state = InterviewState.INTRO
            self.start_time = time.time()
            print(f"  [Interview] Started — State: {self.state.value}")

    def get_next_question(self) -> Optional[str]:
        """Get the next question based on current state and phase."""
        phase = self._state_to_phase()
        if not phase:
            return None

        questions = self._phase_questions.get(phase, [])
        idx = self._phase_idx.get(phase, 0)

        if idx < len(questions):
            self._current_question = questions[idx]
            self._phase_idx[phase] = idx + 1
            self.current_question_idx += 1
            return self._current_question

        # Phase exhausted — advance to next state
        self._advance_state()
        return self.get_next_question()

    def get_current_question(self) -> str:
        return self._current_question

    def process_answer(self, answer_text: str, confidence_data: dict) -> dict:
        """
        Process candidate's answer and decide what to do next.
        Returns an action dict for the LLM to act on.
        """
        quality = self._assess_answer_quality(answer_text, confidence_data)
        self._answer_quality.append(quality)

        # Adaptive difficulty adjustment
        if self.config.difficulty == "adaptive":
            self._adapt_difficulty(quality)

        # Decide action
        if quality < 3.0 and self.state != InterviewState.CLOSING:
            # Weak answer — ask a follow-up to probe deeper
            return {
                "type": "followup",
                "reason": "shallow_answer",
                "quality": quality,
                "difficulty": self._current_difficulty,
                "hint": "Ask a follow-up to probe deeper. Be encouraging but firm.",
            }
        elif quality < 5.0 and random.random() < 0.4:
            # Mediocre — sometimes probe
            return {
                "type": "followup",
                "reason": "needs_elaboration",
                "quality": quality,
                "difficulty": self._current_difficulty,
                "hint": "Ask them to elaborate with a specific example.",
            }
        else:
            # Good enough — move to next question
            self._advance_state_if_needed()
            next_q = self.get_next_question()
            if next_q:
                return {
                    "type": "next_question",
                    "question": next_q,
                    "quality": quality,
                    "difficulty": self._current_difficulty,
                    "state": self.state.value,
                }
            else:
                self.state = InterviewState.COMPLETE
                return {
                    "type": "complete",
                    "quality": quality,
                }

    def record_exchange(self, candidate_text: str, interviewer_text: str):
        """Store the exchange in the transcript."""
        self._transcript.append({
            "question_idx": self.current_question_idx,
            "question": self._current_question,
            "candidate": candidate_text,
            "interviewer": interviewer_text,
            "timestamp": time.time(),
            "state": self.state.value,
            "difficulty": self._current_difficulty,
        })

    def get_transcript(self) -> list[dict]:
        return self._transcript

    def get_recent_exchanges(self, n: int = 2) -> list[dict]:
        return self._transcript[-n:]

    def is_complete(self) -> bool:
        return self.state == InterviewState.COMPLETE

    # ── Private helpers ──

    def _state_to_phase(self) -> Optional[str]:
        mapping = {
            InterviewState.INTRO:      "intro",
            InterviewState.BEHAVIORAL: "behavioral",
            InterviewState.SCENARIO:   "scenario",
            InterviewState.CLOSING:    "closing",
        }
        return mapping.get(self.state)

    def _advance_state(self):
        """Move to the next interview phase."""
        transitions = {
            InterviewState.INTRO:      InterviewState.BEHAVIORAL,
            InterviewState.BEHAVIORAL: InterviewState.SCENARIO,
            InterviewState.FOLLOWUP:   InterviewState.SCENARIO,
            InterviewState.SCENARIO:   InterviewState.CLOSING,
            InterviewState.CLOSING:    InterviewState.COMPLETE,
        }
        prev = self.state
        self.state = transitions.get(self.state, InterviewState.COMPLETE)
        if prev != self.state:
            print(f"  [Interview] Phase transition: {prev.value} → {self.state.value}")

    def _advance_state_if_needed(self):
        """Check if we should move to the next phase based on question count."""
        if self.current_question_idx >= self.config.num_questions - 1:
            self.state = InterviewState.CLOSING

    def _assess_answer_quality(self, text: str, confidence_data: dict) -> float:
        """
        Quick heuristic quality score (0-10).
        The LLM will do deeper analysis, but this drives adaptive behavior.
        """
        score = 5.0  # Baseline

        word_count = len(text.split())

        # Length scoring
        if word_count < 10:
            score -= 2.0   # Very short answer
        elif word_count < 25:
            score -= 0.5
        elif word_count > 50:
            score += 1.0   # Detailed answer
        elif word_count > 100:
            score += 1.5

        # Confidence factor
        conf = confidence_data.get("score", 5)
        score += (conf - 5) * 0.3  # Slight boost/penalty from confidence

        # STAR method indicators (for behavioral)
        star_keywords = ["situation", "task", "action", "result", "outcome",
                         "example", "specifically", "learned", "achieved"]
        star_hits = sum(1 for kw in star_keywords if kw in text.lower())
        score += min(star_hits * 0.3, 1.5)

        # Vague answer penalty
        vague_phrases = ["i think", "maybe", "i guess", "not sure", "i don't know",
                         "it depends", "kind of", "sort of"]
        vague_hits = sum(1 for p in vague_phrases if p in text.lower())
        score -= vague_hits * 0.4

        return max(0, min(10, score))

    def _adapt_difficulty(self, quality: float):
        """Adjust difficulty based on running performance."""
        if quality >= 7:
            self._consecutive_good += 1
            self._consecutive_weak  = 0
            if self._consecutive_good >= 2:
                self._current_difficulty = "hard"
        elif quality <= 3:
            self._consecutive_weak += 1
            self._consecutive_good  = 0
            if self._consecutive_weak >= 2:
                self._current_difficulty = "easy"
        else:
            self._consecutive_good = 0
            self._consecutive_weak = 0
            self._current_difficulty = "medium"

        print(f"  [Adaptive] Difficulty → {self._current_difficulty} "
              f"(quality={quality:.1f}, good_streak={self._consecutive_good}, "
              f"weak_streak={self._consecutive_weak})")
