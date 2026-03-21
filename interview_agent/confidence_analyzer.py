"""
CONFIDENCE ANALYZER
====================
Analyzes candidate confidence from multiple signals:
  1. Speech rate (words per minute)
  2. Filler word frequency (um, uh, like, you know)
  3. Pause/hesitation patterns
  4. Response latency
  5. Voice energy consistency (RMS variation)
  6. Answer completeness signals
"""

import time
import numpy as np
from collections import deque
from typing import Optional

SAMPLE_RATE = 16000

# Filler words that indicate hesitation/low confidence
FILLER_WORDS = {
    "um", "uh", "uhm", "hmm", "erm", "ah",
    "like", "basically", "actually", "literally",
    "you know", "i mean", "kind of", "sort of",
    "right", "so yeah", "and yeah",
}

# Ideal speech rate range (words per minute)
IDEAL_WPM_LOW  = 120
IDEAL_WPM_HIGH = 160


class ConfidenceAnalyzer:
    """
    Analyzes candidate confidence through voice and text signals.
    Produces per-utterance and aggregate scores.
    """

    def __init__(self):
        self._utterance_scores: list[dict] = []
        self._events: list[dict] = []
        self._total_words  = 0
        self._total_fillers = 0
        self._response_times: list[float] = []

    def reset(self):
        self._utterance_scores = []
        self._events = []
        self._total_words  = 0
        self._total_fillers = 0
        self._response_times = []

    def analyze_utterance(
        self,
        text: str,
        audio_bytes: bytes,
        duration_ms: float,
        response_time_sec: float,
    ) -> dict:
        """
        Analyze a single candidate utterance.
        Returns a dict with confidence metrics.
        """
        words = text.lower().split()
        word_count = len(words)
        self._total_words += word_count

        # ── 1. Filler word detection ──
        filler_count = 0
        text_lower = text.lower()
        for filler in FILLER_WORDS:
            if " " in filler:
                filler_count += text_lower.count(filler)
            else:
                filler_count += words.count(filler)
        self._total_fillers += filler_count

        filler_rate = filler_count / max(word_count, 1)

        # ── 2. Speech rate (WPM) ──
        duration_min = duration_ms / 60000
        speech_rate  = word_count / max(duration_min, 0.01)

        # ── 3. Voice energy analysis ──
        pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        energy_stats = self._analyze_energy(pcm)

        # ── 4. Hesitation detection ──
        hesitation_score = self._detect_hesitation(pcm, duration_ms)

        # ── 5. Response latency ──
        if response_time_sec > 0:
            self._response_times.append(response_time_sec)

        # ── Composite Confidence Score (0-10) ──
        score = 5.0  # Baseline

        # Speech rate factor (-2 to +1)
        if speech_rate < 80:
            score -= 2.0  # Very slow — nervous/uncertain
        elif speech_rate < IDEAL_WPM_LOW:
            score -= 1.0
        elif speech_rate <= IDEAL_WPM_HIGH:
            score += 1.0  # Ideal range
        elif speech_rate <= 200:
            score += 0.5  # Slightly fast but acceptable
        else:
            score -= 1.0  # Too fast — nervous rambling

        # Filler word factor (-2 to 0)
        if filler_rate > 0.15:
            score -= 2.0  # Heavy fillers
        elif filler_rate > 0.08:
            score -= 1.0
        elif filler_rate > 0.04:
            score -= 0.5

        # Hesitation factor (-1.5 to 0)
        score -= hesitation_score * 1.5

        # Response time factor (-1 to +0.5)
        if response_time_sec > 0:
            if response_time_sec < 2:
                score += 0.5  # Quick, confident response
            elif response_time_sec > 15:
                score -= 1.0  # Very long pause before answering
            elif response_time_sec > 8:
                score -= 0.5

        # Energy consistency factor (-0.5 to +0.5)
        if energy_stats["cv"] < 0.5:
            score += 0.5   # Steady voice — confident
        elif energy_stats["cv"] > 1.5:
            score -= 0.5   # Highly variable — nervous

        # Word count factor
        if word_count < 5:
            score -= 1.5   # Almost no answer
        elif word_count > 30:
            score += 0.5   # Detailed response

        score = max(0, min(10, score))

        result = {
            "score": round(score, 1),
            "filler_count": filler_count,
            "filler_rate": round(filler_rate, 3),
            "speech_rate": round(speech_rate, 0),
            "word_count": word_count,
            "response_time_sec": round(response_time_sec, 1),
            "hesitation_score": round(hesitation_score, 2),
            "energy_cv": round(energy_stats["cv"], 2),
            "energy_mean": round(energy_stats["mean"], 1),
        }

        self._utterance_scores.append(result)
        return result

    def record_event(self, event_type: str):
        """Record behavioral events (interruption, long_silence, etc.)."""
        self._events.append({
            "type": event_type,
            "timestamp": time.time(),
        })

    def get_summary(self) -> dict:
        """Get aggregate confidence metrics across all utterances."""
        if not self._utterance_scores:
            return {"overall_score": 0, "utterance_count": 0}

        scores = [u["score"] for u in self._utterance_scores]
        rates  = [u["speech_rate"] for u in self._utterance_scores]

        # Trend: are they getting more or less confident?
        trend = "stable"
        if len(scores) >= 3:
            first_half  = np.mean(scores[:len(scores)//2])
            second_half = np.mean(scores[len(scores)//2:])
            if second_half - first_half > 1.0:
                trend = "improving"
            elif first_half - second_half > 1.0:
                trend = "declining"

        return {
            "overall_score": round(float(np.mean(scores)), 1),
            "min_score": round(float(np.min(scores)), 1),
            "max_score": round(float(np.max(scores)), 1),
            "avg_speech_rate": round(float(np.mean(rates)), 0),
            "total_fillers": self._total_fillers,
            "total_words": self._total_words,
            "filler_percentage": round(self._total_fillers / max(self._total_words, 1) * 100, 1),
            "avg_response_time": round(float(np.mean(self._response_times)), 1) if self._response_times else 0,
            "trend": trend,
            "utterance_count": len(self._utterance_scores),
            "events": self._events,
            "per_utterance": self._utterance_scores,
        }

    def _analyze_energy(self, pcm: np.ndarray) -> dict:
        """Analyze voice energy (RMS) variation."""
        if len(pcm) < SAMPLE_RATE // 4:
            return {"mean": 0, "std": 0, "cv": 0}

        # Compute RMS in 100ms windows
        window_size = SAMPLE_RATE // 10  # 100ms
        rms_values = []
        for i in range(0, len(pcm) - window_size, window_size):
            window = pcm[i:i + window_size]
            rms = float(np.sqrt(np.mean(window ** 2)))
            if rms > 50:  # Skip silence windows
                rms_values.append(rms)

        if not rms_values:
            return {"mean": 0, "std": 0, "cv": 0}

        mean_rms = float(np.mean(rms_values))
        std_rms  = float(np.std(rms_values))
        cv = std_rms / max(mean_rms, 1)  # Coefficient of variation

        return {"mean": mean_rms, "std": std_rms, "cv": cv}

    def _detect_hesitation(self, pcm: np.ndarray, duration_ms: float) -> float:
        """
        Detect mid-speech hesitation (pauses within the utterance).
        Returns 0-1 hesitation score.
        """
        if len(pcm) < SAMPLE_RATE:
            return 0.0

        # Count silence gaps (below threshold) within the utterance
        threshold = 100
        window_size = SAMPLE_RATE // 20  # 50ms windows
        total_windows = 0
        silence_windows = 0

        for i in range(0, len(pcm) - window_size, window_size):
            window = pcm[i:i + window_size]
            rms = float(np.sqrt(np.mean(window ** 2)))
            total_windows += 1
            if rms < threshold:
                silence_windows += 1

        if total_windows == 0:
            return 0.0

        # Silence ratio within the utterance (excluding start/end)
        # Trim first and last 10% to avoid start/end silence
        trim = max(1, total_windows // 10)
        mid_start = trim
        mid_end = total_windows - trim

        mid_silence = 0
        mid_total = 0
        window_idx = 0
        for i in range(0, len(pcm) - window_size, window_size):
            if mid_start <= window_idx < mid_end:
                window = pcm[i:i + window_size]
                rms = float(np.sqrt(np.mean(window ** 2)))
                mid_total += 1
                if rms < threshold:
                    mid_silence += 1
            window_idx += 1

        if mid_total == 0:
            return 0.0

        silence_ratio = mid_silence / mid_total
        # Normalize: 0-20% silence is normal, 40%+ is high hesitation
        hesitation = max(0, (silence_ratio - 0.2)) / 0.3
        return min(1.0, hesitation)
