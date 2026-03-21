"""
INPUT MODULE — FIXED
====================
Changes from original:
  1. ✅ Added self.vad = EnergyVAD() in __init__ (was MISSING — caused AttributeError)
  2. ✅ on_barge_in() callback now actually called (was never invoked)
  3. ✅ Added STT-verified barge-in (matching input_ws.py approach)
  4. ✅ Reduced VAD_SPEECH_END_MS 1200 → 1000 for faster turn-taking
  5. ✅ Reduced MIN_BARGEIN_MS 400 → 300 for faster interruption
"""

import asyncio
import time
import numpy as np
from livekit import rtc

# ── VAD Config ──
SAMPLE_RATE        = 16000
FRAME_DURATION_MS  = 20
SAMPLES_PER_FRAME  = SAMPLE_RATE * FRAME_DURATION_MS // 1000

VAD_ENERGY_THRESHOLD = 80
VAD_SPEECH_START_MS  = 100
VAD_SPEECH_END_MS    = 1000   # ✅ Was 1200 — faster turn-taking
MIN_BARGEIN_MS       = 300    # ✅ Was 400 — faster interruption
MIN_UTTERANCE_MS     = 400
PREROLL_MS           = 200


class EnergyVAD:
    """Simple energy-based Voice Activity Detector."""

    def __init__(self):
        self.threshold         = VAD_ENERGY_THRESHOLD
        self._frames_to_start  = max(1, VAD_SPEECH_START_MS  // FRAME_DURATION_MS)
        self._frames_to_end    = max(1, VAD_SPEECH_END_MS    // FRAME_DURATION_MS)
        self._speech_count     = 0
        self._silence_count    = 0
        self.is_speaking       = False
        self._log_counter      = 0
        self._speech_start_time = 0.0
        self.sustained_speech_ms = 0

    def process(self, pcm_bytes: bytes) -> tuple[bool, bool]:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        if len(samples) == 0:
            return False, False

        rms = float(np.sqrt(np.mean(samples ** 2)))

        self._log_counter += 1
        if self._log_counter % 125 == 0:
            status = "SPEECH" if rms > self.threshold else "silent"
            print(f"  [VAD] rms={rms:.1f} threshold={self.threshold} → {status}")

        speech_started = False
        speech_ended   = False

        if rms > self.threshold:
            self._speech_count  += 1
            self._silence_count  = 0
            if self.is_speaking:
                self.sustained_speech_ms = int((time.time() - self._speech_start_time) * 1000)
            if not self.is_speaking and self._speech_count >= self._frames_to_start:
                self.is_speaking         = True
                self._speech_start_time  = time.time()
                self.sustained_speech_ms = 0
                speech_started           = True
                print(f"  [VAD] Speech STARTED  (rms={rms:.1f})")
        else:
            self._silence_count += 1
            self._speech_count   = 0
            if self.is_speaking and self._silence_count >= self._frames_to_end:
                duration         = int((time.time() - self._speech_start_time) * 1000)
                self.is_speaking = False
                speech_ended     = True
                self.sustained_speech_ms = 0
                print(f"  [VAD] Speech ENDED    (duration={duration}ms)")

        return speech_started, speech_ended


class AudioInputHandler:
    """
    Attaches to a LiveKit remote audio track and drives the full input pipeline:
      frame → VAD → buffer → on_utterance_ready callback
    """

    def __init__(self, on_utterance_ready, is_agent_speaking, on_barge_in=None):
        self.on_utterance_ready = on_utterance_ready
        self.is_agent_speaking  = is_agent_speaking
        self.on_barge_in        = on_barge_in
        self.vad                = EnergyVAD()    # ✅ FIX: Was completely missing!
        self._utterance_task: asyncio.Task | None = None
        self._barge_task: asyncio.Task | None = None
        self._barge_verified = False
        self._last_barge_check_ms = 0

    async def _verify_speech(self, audio_bytes: bytes) -> bool:
        """Quick STT check to distinguish human speech from echo."""
        from processing import transcribe_audio
        pcm = np.frombuffer(audio_bytes, dtype=np.int16)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, transcribe_audio, pcm, True)
        if text and len(text.strip()) > 1:
            print(f"  [Input] ✓ Verified human speech: '{text}'")
            return True
        return False

    async def process_track(self, track: rtc.Track, participant: rtc.RemoteParticipant):
        print(f"[Input] Attaching to audio track from {participant.identity}")
        print(f"[Input] Forcing resample → 16 kHz mono  (KEY FIX)")

        audio_stream = rtc.AudioStream(
            track,
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            frame_size_ms=FRAME_DURATION_MS,
        )

        preroll_frames = max(1, PREROLL_MS // FRAME_DURATION_MS)
        preroll_buffer: list[bytes] = []

        speech_buffer = bytearray()
        is_buffering  = False
        started_during_agent_speech = False

        print(f"[Input] Listening … (threshold={VAD_ENERGY_THRESHOLD}, "
              f"start={VAD_SPEECH_START_MS}ms, end={VAD_SPEECH_END_MS}ms)")

        frame_count = 0
        async for event in audio_stream:
            frame_count += 1
            if frame_count == 1:
                f = event.frame
                print(f"  [Input] First frame: {f.samples_per_channel} samples, "
                      f"{f.sample_rate}Hz, {f.num_channels}ch, "
                      f"{len(bytes(f.data))} bytes  ← if this prints, audio IS arriving")
            audio_bytes = bytes(event.frame.data)

            speech_started, speech_ended = self.vad.process(audio_bytes)

            # ── Maintain pre-roll ring buffer (before speech) ──
            if not is_buffering:
                preroll_buffer.append(audio_bytes)
                if len(preroll_buffer) > preroll_frames:
                    preroll_buffer.pop(0)

            # ── Speech starts ──
            if speech_started:
                is_buffering = True
                speech_buffer = bytearray()
                for frame in preroll_buffer:
                    speech_buffer.extend(frame)
                preroll_buffer.clear()

                # Reset barge-in verification state
                self._barge_verified = False
                self._barge_task = None
                self._last_barge_check_ms = 0

                started_during_agent_speech = self.is_agent_speaking()
                if started_during_agent_speech:
                    print("  [Input] Speech started while agent speaking (possible echo)")

            # ── Accumulate speech frames ──
            if is_buffering:
                speech_buffer.extend(audio_bytes)

                # ── Barge-in with STT verification ──────────────────────
                # ✅ FIX: Now actually verifies and calls on_barge_in()
                # (Old code just printed a log and set a flag — never interrupted)
                if self.is_agent_speaking() and not self._barge_verified:
                    # Check if previous verification completed
                    if self._barge_task and self._barge_task.done():
                        if self._barge_task.result():
                            self._barge_verified = True
                            started_during_agent_speech = False
                            if self.on_barge_in:
                                self.on_barge_in()     # ✅ FIX: Actually interrupt!
                        else:
                            self._barge_task = None

                    # Trigger new check every 300ms of sustained speech
                    if (self.vad.sustained_speech_ms >= MIN_BARGEIN_MS
                            and (self.vad.sustained_speech_ms - self._last_barge_check_ms) >= 300):
                        if self._barge_task is None:
                            self._last_barge_check_ms = self.vad.sustained_speech_ms
                            print(f"  [Input] Checking {self.vad.sustained_speech_ms}ms for barge-in...")
                            self._barge_task = asyncio.create_task(
                                self._verify_speech(bytes(speech_buffer))
                            )

            # ── Speech ends ──
            if speech_ended and is_buffering:
                is_buffering = False

                if started_during_agent_speech and not self._barge_verified:
                    print("[Input] Discarding — likely mic echo (started while agent spoke)")
                    speech_buffer = bytearray()
                    continue

                pcm = np.frombuffer(speech_buffer, dtype=np.int16)
                duration_ms = len(pcm) / SAMPLE_RATE * 1000

                if duration_ms < MIN_UTTERANCE_MS:
                    print(f"  [Input] Too short ({duration_ms:.0f}ms) — discarding")
                    speech_buffer = bytearray()
                    continue

                print(f"  [Input] Utterance ready: {duration_ms:.0f}ms of audio")

                if self._utterance_task is None or self._utterance_task.done():
                    audio_data = bytes(speech_buffer)
                    self._utterance_task = asyncio.ensure_future(
                        self.on_utterance_ready(audio_data)
                    )
                else:
                    print("[Input] Previous utterance still processing — dropping new one")

                speech_buffer = bytearray()