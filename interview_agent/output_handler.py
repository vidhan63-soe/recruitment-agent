"""
OUTPUT MODULE — AI Interviewer
================================
TTS Pipeline:
  PRIMARY:  SarvamAI Bulbul v2 (Indian English, WebSocket streaming, ₹1000 free)
  FALLBACK: Coqui VITS (fully local, no API needed)

Features:
  - Smart chunking for long sentences
  - Overlap synthesis with playback
  - Barge-in / interruption support
  - Transcript publishing via LiveKit data channel
"""

import asyncio
import json
import os
import re
import tempfile
import wave
import io
import base64
import numpy as np
from typing import Optional

# ── Config ──────────────────────────────────────────────────────────────────
SAMPLE_RATE       = 16000
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000

VITS_SPEAKER   = "p251"
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
USE_SARVAM_TTS = bool(SARVAM_API_KEY)

# ════════════════════════════════════════════════════
# TTS Engines
# ════════════════════════════════════════════════════

# --- SarvamAI TTS (Primary — better Indian English) ---
_sarvam_tts = None
if USE_SARVAM_TTS:
    try:
        from sarvamai import SarvamAI
        _sarvam_tts = SarvamAI(api_subscription_key=SARVAM_API_KEY)
        print(f"[Output] ✓ SarvamAI TTS (Bulbul v2) — Indian English")
    except ImportError:
        print("[Output] ⚠ sarvamai not installed — using Coqui VITS only")
        USE_SARVAM_TTS = False

# --- Coqui VITS (Fallback — fully local) ---
print("[Output] Loading Coqui VITS (fallback TTS) …")
try:
    from TTS.api import TTS as CoquiTTS
    _coqui_tts = CoquiTTS("tts_models/en/vctk/vits")
    _COQUI_SAMPLE_RATE = 22050
    print(f"  ✓ Coqui VITS loaded (speaker={VITS_SPEAKER})")
except Exception as e:
    print(f"  ⚠ Coqui TTS failed: {e}")
    _coqui_tts = None

print("[Output] TTS ready.\n")

_current_speaker = VITS_SPEAKER

def set_speaker(speaker_id: str):
    global _current_speaker
    _current_speaker = speaker_id
    print(f"[Output] Speaker changed to: {speaker_id}")


# ════════════════════════════════════════════════════
# TTS Synthesis
# ════════════════════════════════════════════════════
def synthesize_speech(text: str) -> np.ndarray:
    """text → 16kHz int16 PCM numpy array. Tries SarvamAI first, then Coqui."""

    # Try SarvamAI first (better quality for Indian English)
    if USE_SARVAM_TTS and _sarvam_tts:
        try:
            return _synthesize_sarvam(text)
        except Exception as e:
            print(f"  [TTS] SarvamAI error, falling back to Coqui: {e}")

    # Fallback to Coqui VITS
    if _coqui_tts:
        return _synthesize_coqui(text)

    # Last resort: silence
    print("  [TTS] No TTS engine available!")
    return np.zeros(SAMPLE_RATE, dtype=np.int16)


def _synthesize_sarvam(text: str) -> np.ndarray:
    """Synthesize using SarvamAI Bulbul TTS."""
    response = _sarvam_tts.text_to_speech.convert(
        text=text,
        target_language_code="en-IN",
        model="bulbul:v2",
        speaker="meera",  # Professional female voice
        speech_sample_rate=16000,
        enable_preprocessing=True,
    )

    # Decode base64 audio
    if hasattr(response, "audios") and response.audios:
        audio_b64 = response.audios[0]
        audio_bytes = base64.b64decode(audio_b64)
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        return audio
    elif hasattr(response, "audio_content"):
        audio_bytes = base64.b64decode(response.audio_content)
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        return audio

    raise ValueError("Unexpected SarvamAI TTS response format")


def _synthesize_coqui(text: str) -> np.ndarray:
    """Synthesize using local Coqui VITS."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name

    try:
        _coqui_tts.tts_to_file(text=text, file_path=tmp, speaker=_current_speaker)

        with wave.open(tmp, "rb") as wf:
            raw      = wf.readframes(wf.getnframes())
            src_rate = wf.getframerate()

        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

        if src_rate != SAMPLE_RATE:
            target_len = int(len(audio) * SAMPLE_RATE / src_rate)
            indices    = np.linspace(0, len(audio) - 1, target_len).astype(int)
            audio      = audio[indices]

        return audio.astype(np.int16)
    finally:
        os.unlink(tmp)


# ════════════════════════════════════════════════════
# Smart TTS Chunking
# ════════════════════════════════════════════════════
MAX_TTS_WORDS   = 18
MIN_CHUNK_WORDS = 5

def _split_for_tts(text: str) -> list[str]:
    """Split text into TTS-friendly chunks."""
    words = text.split()
    if len(words) <= MAX_TTS_WORDS:
        return [text]

    chunks = []
    remaining = text.strip()

    while remaining:
        remaining_words = remaining.split()
        if len(remaining_words) <= MAX_TTS_WORDS:
            if chunks and len(remaining_words) < MIN_CHUNK_WORDS:
                chunks[-1] = chunks[-1] + " " + remaining.strip()
            else:
                chunks.append(remaining.strip())
            break

        search_text = " ".join(remaining_words[:MAX_TTS_WORDS + 5])
        best_pos = -1
        target_chars = len(" ".join(remaining_words[:MAX_TTS_WORDS]))
        min_chars = len(" ".join(remaining_words[:MIN_CHUNK_WORDS]))

        for i, ch in enumerate(search_text):
            if ch in ',;:' and i > min_chars and i <= target_chars + 20:
                best_pos = i + 1

        if best_pos == -1:
            conj_pattern = re.compile(r'\s(and|but|or|however|while|because|which)\s', re.IGNORECASE)
            for m in conj_pattern.finditer(search_text):
                if m.start() > min_chars and m.start() <= target_chars + 20:
                    best_pos = m.start()
                    break

        if best_pos > min_chars and best_pos < len(remaining):
            chunks.append(remaining[:best_pos].strip())
            remaining = remaining[best_pos:].strip()
        else:
            chunks.append(" ".join(remaining_words[:MAX_TTS_WORDS]))
            remaining = " ".join(remaining_words[MAX_TTS_WORDS:])

    return [c for c in chunks if c.strip()]


# ════════════════════════════════════════════════════
# Audio Output Handler
# ════════════════════════════════════════════════════
class AudioOutputHandler:
    """LiveKit audio output with queueing, chunked TTS, and interruption."""

    def __init__(self, audio_source, room):
        from livekit import rtc
        self.audio_source   = audio_source
        self.room           = room
        self.queue          = asyncio.Queue()
        self._playback_task = asyncio.ensure_future(self._playback_loop())
        self._current_speak_task = None
        self._interrupted   = False
        self.is_speaking    = False
        self.on_done: callable | None = None

    def speak(self, text: str):
        self.queue.put_nowait(text)

    def interrupt(self):
        self._interrupted = True
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
        if self._current_speak_task and not self._current_speak_task.done():
            self._current_speak_task.cancel()

    async def _playback_loop(self):
        while True:
            text = await self.queue.get()
            self._interrupted = False
            self.is_speaking = True

            try:
                self._current_speak_task = asyncio.create_task(self._process_and_play(text))
                await self._current_speak_task
            except asyncio.CancelledError:
                pass
            finally:
                self.queue.task_done()
                if self.queue.empty():
                    self.is_speaking = False
                    if self.on_done and not self._interrupted:
                        self.on_done()

    async def _process_and_play(self, text: str):
        chunks = _split_for_tts(text)

        if len(chunks) == 1:
            loop = asyncio.get_event_loop()
            pcm = await loop.run_in_executor(None, synthesize_speech, text)
            if self._interrupted:
                return
            await self._send_transcript("interviewer", text)
            await self._publish_pcm(pcm)
        else:
            await self._send_transcript("interviewer", text)
            loop = asyncio.get_event_loop()
            next_pcm = await loop.run_in_executor(None, synthesize_speech, chunks[0])

            for i, chunk in enumerate(chunks):
                if self._interrupted:
                    return
                current_pcm = next_pcm
                synth_task = None
                if i + 1 < len(chunks):
                    synth_task = loop.run_in_executor(None, synthesize_speech, chunks[i + 1])
                await self._publish_pcm(current_pcm)
                if synth_task:
                    next_pcm = await synth_task

    async def _publish_pcm(self, pcm: np.ndarray):
        from livekit import rtc
        for i in range(0, len(pcm), SAMPLES_PER_FRAME):
            if self._interrupted:
                break
            chunk = pcm[i: i + SAMPLES_PER_FRAME]
            if len(chunk) < SAMPLES_PER_FRAME:
                chunk = np.pad(chunk, (0, SAMPLES_PER_FRAME - len(chunk)))

            frame = rtc.AudioFrame(
                data=chunk.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=SAMPLES_PER_FRAME,
            )
            await self.audio_source.capture_frame(frame)
            await asyncio.sleep(FRAME_DURATION_MS / 1000)

    async def _send_transcript(self, role: str, text: str):
        try:
            payload = json.dumps({"type": "transcript", "role": role, "text": text})
            await self.room.local_participant.publish_data(
                payload.encode("utf-8"), reliable=True
            )
        except Exception as e:
            print(f"  [Output] Transcript send error: {e}")
