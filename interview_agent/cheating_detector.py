"""
CHEATING DETECTOR
==================
Detects potential dishonesty during the interview:

  FRONTEND SIGNALS (reported via API):
    - Tab switching (alt-tab, focus loss)
    - Copy-paste events
    - Screen sharing detection
    - Typing sounds during voice interview
    - Multiple browser tabs
    - DevTools open

  VOICE/TEXT SIGNALS (analyzed here):
    - Suspiciously perfect/rehearsed answers
    - Inconsistent response timing (too fast = reading, too slow = searching)
    - Answer contradictions with earlier responses
    - Vocabulary mismatch (sudden sophistication jump)
    - Reading cadence detection (unnaturally even pace)
"""

import time
import re
from collections import defaultdict
from typing import Optional


class CheatingDetector:
    """
    Multi-signal cheating detection system.
    Flags are cumulative — individual signals are weak,
    but patterns across signals create strong indicators.
    """

    def __init__(self):
        self._frontend_signals: list[dict] = []
        self._voice_signals: list[dict] = []
        self._response_history: list[dict] = []
        self._flag_count = 0
        self._severity_score = 0.0  # 0-100

    def reset(self):
        self._frontend_signals = []
        self._voice_signals = []
        self._response_history = []
        self._flag_count = 0
        self._severity_score = 0.0

    def add_frontend_signal(self, signal_type: str, details: dict = None):
        """
        Record a cheating signal from the frontend.
        Types: tab_switch, copy_paste, devtools, focus_loss,
               typing_detected, screen_share, multiple_tabs, disconnect
        """
        signal = {
            "type": signal_type,
            "details": details or {},
            "timestamp": time.time(),
        }
        self._frontend_signals.append(signal)

        # Weight different signals
        weights = {
            "tab_switch": 3,
            "copy_paste": 5,
            "devtools": 4,
            "focus_loss": 2,
            "typing_detected": 3,
            "screen_share": 1,  # Could be legitimate
            "multiple_tabs": 2,
            "disconnect": 1,
        }

        weight = weights.get(signal_type, 1)
        self._severity_score += weight
        self._flag_count += 1

        print(f"  [Cheating] Frontend signal: {signal_type} "
              f"(severity +{weight} → {self._severity_score:.0f})")

    def analyze_response(
        self,
        text: str,
        response_time_sec: float,
        question_context: str,
    ):
        """
        Analyze a candidate response for cheating indicators.
        """
        entry = {
            "text": text,
            "response_time": response_time_sec,
            "question": question_context,
            "timestamp": time.time(),
            "word_count": len(text.split()),
            "flags": [],
        }

        # ── 1. Response timing analysis ──
        if response_time_sec > 0:
            # Suspiciously fast for a complex answer
            words = len(text.split())
            if words > 50 and response_time_sec < 3:
                entry["flags"].append("suspiciously_fast_detailed_answer")
                self._severity_score += 4
                print(f"  [Cheating] Suspiciously fast detailed answer "
                      f"({words} words in {response_time_sec:.1f}s)")

        # ── 2. Reading cadence detection ──
        # Natural speech has variable word lengths and pauses
        # Reading aloud tends to be more even
        if self._detect_reading_pattern(text):
            entry["flags"].append("possible_reading")
            self._severity_score += 2
            print("  [Cheating] Possible reading pattern detected")

        # ── 3. Vocabulary sophistication jump ──
        if self._response_history:
            if self._detect_vocabulary_jump(text):
                entry["flags"].append("vocabulary_jump")
                self._severity_score += 3
                print("  [Cheating] Sudden vocabulary sophistication jump")

        # ── 4. Contradiction detection ──
        contradiction = self._detect_contradictions(text)
        if contradiction:
            entry["flags"].append(f"contradiction: {contradiction}")
            self._severity_score += 2
            print(f"  [Cheating] Possible contradiction: {contradiction}")

        # ── 5. Perfect answer detection ──
        # Suspiciously textbook-like answers
        if self._detect_textbook_answer(text):
            entry["flags"].append("textbook_answer")
            self._severity_score += 2
            print("  [Cheating] Textbook-like answer detected")

        # ── 6. Temporal correlation with frontend signals ──
        # If tab switch happened right before this answer, that's suspicious
        recent_tab_switches = [
            s for s in self._frontend_signals
            if s["type"] in ("tab_switch", "focus_loss", "copy_paste")
            and time.time() - s["timestamp"] < 30  # Within last 30 seconds
        ]
        if recent_tab_switches:
            entry["flags"].append(f"correlated_with_{len(recent_tab_switches)}_frontend_signals")
            self._severity_score += len(recent_tab_switches) * 2

        self._response_history.append(entry)
        if entry["flags"]:
            self._flag_count += len(entry["flags"])

    def get_flags(self) -> dict:
        """Get current cheating detection summary."""
        # Determine overall risk level
        if self._severity_score >= 30:
            risk = "high"
        elif self._severity_score >= 15:
            risk = "medium"
        elif self._severity_score >= 5:
            risk = "low"
        else:
            risk = "none"

        return {
            "risk_level": risk,
            "severity_score": round(self._severity_score, 1),
            "total_flags": self._flag_count,
            "frontend_signals": len(self._frontend_signals),
            "frontend_details": self._summarize_frontend(),
            "voice_flags": self._summarize_voice_flags(),
        }

    def get_detailed_report(self) -> dict:
        """Full report for the final interview evaluation."""
        return {
            "summary": self.get_flags(),
            "frontend_signals": self._frontend_signals,
            "response_analysis": [
                {
                    "question": r["question"][:100],
                    "response_time": r["response_time"],
                    "word_count": r["word_count"],
                    "flags": r["flags"],
                }
                for r in self._response_history
                if r["flags"]
            ],
        }

    # ── Private detection methods ──

    def _detect_reading_pattern(self, text: str) -> bool:
        """
        Detect if text sounds like it's being read aloud vs spoken naturally.
        Reading tends to have: longer sentences, fewer contractions,
        more formal structure, fewer self-corrections.
        """
        words = text.split()
        if len(words) < 20:
            return False

        # Check for very formal structure (no contractions, long sentences)
        contractions = ["i'm", "don't", "won't", "can't", "didn't", "couldn't",
                        "shouldn't", "i've", "i'd", "it's", "that's", "we're"]
        has_contractions = any(c in text.lower() for c in contractions)

        # Check for self-corrections (natural speech)
        corrections = ["i mean", "sorry", "well actually", "let me rephrase",
                       "what i meant", "no wait"]
        has_corrections = any(c in text.lower() for c in corrections)

        # Very formal + no corrections + long = possibly reading
        sentences = re.split(r'[.!?]', text)
        avg_sentence_len = sum(len(s.split()) for s in sentences if s.strip()) / max(len(sentences), 1)

        if not has_contractions and not has_corrections and avg_sentence_len > 20:
            return True

        return False

    def _detect_vocabulary_jump(self, text: str) -> bool:
        """Detect sudden increase in vocabulary sophistication."""
        if len(self._response_history) < 2:
            return False

        # Simple proxy: average word length
        current_avg_len = sum(len(w) for w in text.split()) / max(len(text.split()), 1)

        prev_lengths = []
        for r in self._response_history[-3:]:
            words = r["text"].split()
            if words:
                prev_lengths.append(sum(len(w) for w in words) / len(words))

        if prev_lengths:
            prev_avg = sum(prev_lengths) / len(prev_lengths)
            # Significant jump in word sophistication
            if current_avg_len > prev_avg * 1.5 and current_avg_len > 6:
                return True

        return False

    def _detect_contradictions(self, text: str) -> Optional[str]:
        """
        Check if current answer contradicts previous statements.
        Simple keyword-based check — LLM does deeper analysis.
        """
        if len(self._response_history) < 2:
            return None

        text_lower = text.lower()

        # Check for factual contradictions (years of experience, technologies, etc.)
        # This is a simplified version — the LLM scoring does deeper analysis
        for prev in self._response_history:
            prev_lower = prev["text"].lower()

            # Year/number contradictions
            current_numbers = re.findall(r'\b(\d+)\s*years?\b', text_lower)
            prev_numbers = re.findall(r'\b(\d+)\s*years?\b', prev_lower)

            if current_numbers and prev_numbers:
                if current_numbers[0] != prev_numbers[0]:
                    return f"experience years mismatch: {prev_numbers[0]} vs {current_numbers[0]}"

        return None

    def _detect_textbook_answer(self, text: str) -> bool:
        """Detect suspiciously perfect, textbook-like answers."""
        textbook_markers = [
            "according to", "research shows", "studies indicate",
            "it is widely acknowledged", "the key principles are",
            "firstly, secondly, thirdly", "in conclusion",
            "the primary objective", "it is imperative",
        ]

        hits = sum(1 for m in textbook_markers if m in text.lower())
        return hits >= 2

    def _summarize_frontend(self) -> dict:
        """Summarize frontend signals by type."""
        counts = defaultdict(int)
        for s in self._frontend_signals:
            counts[s["type"]] += 1
        return dict(counts)

    def _summarize_voice_flags(self) -> list[str]:
        """Collect all unique voice-side flags."""
        flags = set()
        for r in self._response_history:
            for f in r["flags"]:
                flags.add(f.split(":")[0].strip())
        return sorted(flags)
