"""
INPUT WS MODULE — IMPROVED
===========================
Changes from original:
  1. ✅ VAD_SPEECH_END_MS 700 → 500 (faster turn-taking)
  2. ✅ MIN_BARGEIN_MS 400 → 250 (faster interruption)
  3. ✅ Barge check interval 300ms → 200ms
"""

import asyncio
import time
import numpy as np
import aiohttp
from aiohttp import web

# ── VAD Config ───────────────────────────────────────────────────────────────
SAMPLE_RATE        = 16000
FRAME_DURATION_MS  = 20
SAMPLES_PER_FRAME  = SAMPLE_RATE * FRAME_DURATION_MS // 1000

VAD_ENERGY_THRESHOLD = 300
VAD_SPEECH_START_MS  = 100
VAD_SPEECH_END_MS    = 500    # ✅ Was 700 — faster turn-taking
MIN_BARGEIN_MS       = 250    # ✅ Was 400 — faster interruption
MIN_UTTERANCE_MS     = 250
PREROLL_MS           = 200

BARGE_CHECK_INTERVAL_MS = 200  # ✅ Was 300 — check more often

WS_PORT = 5001


class _VAD:
    def __init__(self):
        self._frames_to_start  = max(1, VAD_SPEECH_START_MS  // FRAME_DURATION_MS)
        self._frames_to_end    = max(1, VAD_SPEECH_END_MS    // FRAME_DURATION_MS)
        self._speech_count     = 0
        self._silence_count    = 0
        self.is_speaking       = False
        self._log_ctr          = 0
        self._t_start          = 0.0
        self.sustained_ms      = 0

    def process(self, pcm_bytes: bytes) -> tuple[bool, bool]:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        if not len(samples):
            return False, False
        rms = float(np.sqrt(np.mean(samples ** 2)))

        self._log_ctr += 1
        if self._log_ctr % 125 == 0:
            status = "SPEECH" if rms > VAD_ENERGY_THRESHOLD else "silent"
            print(f"  [WS-VAD] rms={rms:.1f} → {status}  (threshold={VAD_ENERGY_THRESHOLD})")

        started = ended = False
        if rms > VAD_ENERGY_THRESHOLD:
            self._speech_count  += 1
            self._silence_count  = 0
            if self.is_speaking:
                self.sustained_ms = int((time.time() - self._t_start) * 1000)
            if not self.is_speaking and self._speech_count >= self._frames_to_start:
                self.is_speaking = True
                self._t_start    = time.time()
                self.sustained_ms = 0
                started = True
                print(f"  [WS-VAD] *** SPEECH STARTED *** (rms={rms:.1f})")
        else:
            self._silence_count += 1
            self._speech_count   = 0
            if self.is_speaking and self._silence_count >= self._frames_to_end:
                dur = int((time.time() - self._t_start) * 1000)
                self.is_speaking  = False
                self.sustained_ms = 0
                ended = True
                print(f"  [WS-VAD] *** SPEECH ENDED *** (duration={dur}ms)")
        return started, ended


class WSInputHandler:
    def __init__(self, on_utterance_ready, is_agent_speaking, on_barge_in):
        self.on_utterance_ready = on_utterance_ready
        self.is_agent_speaking  = is_agent_speaking
        self.on_barge_in        = on_barge_in
        self._utterance_task: asyncio.Task | None = None

    async def _verify_speech(self, audio_bytes: bytes) -> bool:
        """Runs a fast background STT check on a short audio chunk."""
        from processing import transcribe_audio
        pcm = np.frombuffer(audio_bytes, dtype=np.int16)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, transcribe_audio, pcm, True)
        if text and len(text.strip()) > 1:
            print(f"  [WS-Input] ✓ Verified human speech: '{text}'")
            return True
        return False

    async def start(self):
        try:
            app = web.Application()
            app.router.add_get('/audio', self._ws_handler)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', WS_PORT)
            await site.start()
            print(f"[WS-Input] ✓ WebSocket server listening on ws://0.0.0.0:{WS_PORT}/audio")
            await asyncio.Future()
        except OSError as e:
            print(f"[WS-Input] ✗ Could not bind port {WS_PORT}: {e}")
        except Exception as e:
            print(f"[WS-Input] ✗ Startup failed: {e}")

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)
        remote = request.remote

        vad          = _VAD()
        preroll_cap  = max(1, PREROLL_MS // FRAME_DURATION_MS)
        preroll: list[bytes] = []
        speech_buf   = bytearray()
        is_buf       = False
        started_during_agent = False
        leftover     = bytearray()
        frame_bytes  = SAMPLES_PER_FRAME * 2

        # Verification tracking
        vad_verified  = False
        barge_task    = None
        last_check_ms = 0

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    leftover.extend(msg.data)

                    while len(leftover) >= frame_bytes:
                        frame = bytes(leftover[:frame_bytes])
                        leftover = leftover[frame_bytes:]

                        speech_started, speech_ended = vad.process(frame)

                        if not is_buf:
                            preroll.append(frame)
                            if len(preroll) > preroll_cap:
                                preroll.pop(0)

                        if speech_started:
                            is_buf = True
                            speech_buf = bytearray()
                            for f in preroll:
                                speech_buf.extend(f)
                            preroll.clear()
                            
                            vad_verified  = False
                            barge_task    = None
                            last_check_ms = 0
                            
                            started_during_agent = self.is_agent_speaking()

                        if is_buf:
                            speech_buf.extend(frame)

                            # ── SMART VERIFICATION ──
                            if self.is_agent_speaking() and not vad_verified:
                                
                                if barge_task and barge_task.done():
                                    if barge_task.result() == True:
                                        vad_verified = True
                                        started_during_agent = False
                                        self.on_barge_in()
                                    else:
                                        barge_task = None

                                # ✅ Check every 200ms instead of 300ms
                                if (vad.sustained_ms >= MIN_BARGEIN_MS
                                        and (vad.sustained_ms - last_check_ms) >= BARGE_CHECK_INTERVAL_MS):
                                    if barge_task is None:
                                        last_check_ms = vad.sustained_ms
                                        print(f"  [WS-Input] Checking {vad.sustained_ms}ms of audio for words...")
                                        barge_task = asyncio.create_task(
                                            self._verify_speech(bytes(speech_buf))
                                        )

                        if speech_ended and is_buf:
                            is_buf = False
                            
                            if started_during_agent and not vad_verified:
                                print("[WS-Input] Discarding (Unverified noise or echo)")
                                speech_buf = bytearray()
                                continue

                            pcm = np.frombuffer(speech_buf, dtype=np.int16)
                            dur = len(pcm) / SAMPLE_RATE * 1000
                            if dur < MIN_UTTERANCE_MS:
                                speech_buf = bytearray()
                                continue

                            print(f"  [WS-Input] Utterance ready: {dur:.0f}ms")
                            if self._utterance_task is None or self._utterance_task.done():
                                audio = bytes(speech_buf)
                                self._utterance_task = asyncio.ensure_future(
                                    self.on_utterance_ready(audio)
                                )
                            speech_buf = bytearray()
        finally:
            print(f"[WS-Input] Browser disconnected: {remote}")

        return ws