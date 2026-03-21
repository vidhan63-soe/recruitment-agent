"""
AI INTERVIEWER — Main Orchestrator
====================================
Universal AI Interviewer that conducts structured interviews for ANY role.
Scores candidates on confidence, communication, knowledge, and integrity.

Architecture:
  INPUT  → LiveKit RX / WebSocket → VAD → STT (Whisper local + SarvamAI fallback)
  BRAIN  → Interview State Machine → Groq LLM (fast) / Ollama (fallback)
  OUTPUT → SarvamAI TTS (Indian English) / Coqui VITS (fallback) → LiveKit TX
  SCORE  → Confidence Analyzer + Cheating Detector + Adaptive Difficulty
"""

import asyncio
import time
import threading
import json
import os
import sqlite3

from livekit import api, rtc
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from input_handler import AudioInputHandler
from input_ws     import WSInputHandler
from processing   import (
    transcribe_audio, generate_interview_response_stream,
    extract_candidate_info, InterviewBrain
)
from output_handler import AudioOutputHandler
from interview_engine import InterviewEngine, InterviewConfig
from confidence_analyzer import ConfidenceAnalyzer
from cheating_detector import CheatingDetector
from scoring import ScoringEngine

# ── LiveKit config ─────────────────────────────────────────────────────────
LIVEKIT_URL        = os.getenv("LIVEKIT_URL", "wss://voice-4jhzmt71.livekit.cloud")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY", "APIMwJJEKW5zdT3")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "n5HvVm04pDoquZc8DHOhMG0b5lm1PbFEUYXRnOb6TcK")
ROOM_NAME          = "interview"

# Path to the shared recruitment database
RECRUITMENT_DB = os.path.join(os.path.dirname(__file__), "..", "recruitment.db")


def _get_interview_config_by_token(token: str) -> dict | None:
    """Read interview config from recruitment.db by token (sync, for Flask routes)."""
    try:
        conn = sqlite3.connect(RECRUITMENT_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM interview_sessions WHERE token = ?", (token,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["question_config"] = json.loads(d.get("question_config", "{}"))
            return d
        return None
    except Exception as e:
        print(f"[DB] Could not read interview config: {e}")
        return None


def _mark_interview_active(token: str):
    """Mark interview status as active in the DB."""
    try:
        conn = sqlite3.connect(RECRUITMENT_DB)
        conn.execute(
            "UPDATE interview_sessions SET status = 'active' WHERE token = ? AND status = 'pending'",
            (token,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Could not update interview status: {e}")

SAMPLE_RATE = 16000

SILENCE_TIMEOUT_SEC   = 45  # Shorter for interviews — keep pressure on
MAX_SILENCE_REMINDERS = 2


# ════════════════════════════════════════════════════
# Flask API Server
# ════════════════════════════════════════════════════
flask_app = Flask(__name__, static_folder="static")
CORS(flask_app)

# Global reference to the active interview agent
_active_agent = None


@flask_app.route("/")
def index():
    return send_from_directory("static", "index.html")


@flask_app.route("/api/token")
def get_token():
    identity     = request.args.get("identity", f"candidate-{int(time.time())}")
    room         = request.args.get("room", ROOM_NAME)
    session_token = request.args.get("token", "")  # Interview session token from URL

    interview_config = None
    if session_token:
        interview_data = _get_interview_config_by_token(session_token)
        if interview_data:
            interview_config = interview_data.get("question_config", {})
            # Use candidate name as identity if available
            candidate_name = interview_config.get("candidate_name", "")
            if candidate_name:
                identity = candidate_name.replace(" ", "-").lower()
            _mark_interview_active(session_token)
            print(f"[*] Interview token validated for: {candidate_name or identity}")
        else:
            print(f"[*] Warning: unknown interview token {session_token[:8]}…")

    lk_token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
    )
    return jsonify({
        "token": lk_token.to_jwt(),
        "url": LIVEKIT_URL,
        "room": room,
        "identity": identity,
        "interview_config": interview_config,  # Sent to frontend → used to configure interview
    })


@flask_app.route("/api/interview-session/<token>")
def get_interview_session(token):
    """Return interview config for a given session token (called by candidate frontend)."""
    data = _get_interview_config_by_token(token)
    if not data:
        return jsonify({"error": "Invalid or expired token"}), 404
    return jsonify({
        "candidate_name": data.get("candidate_name", ""),
        "status": data.get("status", "pending"),
        "question_config": data.get("question_config", {}),
    })


@flask_app.route("/api/health")
def health():
    return jsonify({"status": "ok", "mode": "ai-interviewer"})


@flask_app.route("/api/interview/start", methods=["POST"])
def start_interview():
    """Configure and start an interview session."""
    data = request.get_json() or {}
    config = InterviewConfig(
        role=data.get("role", "Software Engineer"),
        experience_level=data.get("experience_level", "mid"),
        domain=data.get("domain", "general"),
        candidate_name=data.get("candidate_name", "Candidate"),
        language=data.get("language", "en"),
        num_questions=data.get("num_questions", 8),
        difficulty=data.get("difficulty", "adaptive"),
    )
    if _active_agent and _active_agent.interview_engine:
        _active_agent.interview_engine.configure(config)
        _active_agent.confidence_analyzer.reset()
        _active_agent.cheating_detector.reset()
        return jsonify({"status": "configured", "config": config.to_dict()})
    return jsonify({"status": "agent_not_ready"}), 503


@flask_app.route("/api/interview/status")
def interview_status():
    """Get current interview state, scores, question number."""
    if _active_agent and _active_agent.interview_engine:
        engine = _active_agent.interview_engine
        return jsonify({
            "state": engine.state.value,
            "current_question": engine.current_question_idx,
            "total_questions": engine.config.num_questions,
            "elapsed_seconds": int(time.time() - engine.start_time) if engine.start_time else 0,
            "confidence_scores": _active_agent.confidence_analyzer.get_summary(),
            "cheating_flags": _active_agent.cheating_detector.get_flags(),
            "transcript": engine.get_transcript(),
        })
    return jsonify({"state": "not_started"})


@flask_app.route("/api/interview/report")
def interview_report():
    """Generate the final detailed interview report."""
    if _active_agent and _active_agent.scoring_engine:
        report = _active_agent.scoring_engine.generate_report(
            interview_engine=_active_agent.interview_engine,
            confidence_analyzer=_active_agent.confidence_analyzer,
            cheating_detector=_active_agent.cheating_detector,
        )
        return jsonify(report)
    return jsonify({"error": "No interview data"}), 404


@flask_app.route("/api/cheating/report", methods=["POST"])
def report_cheating():
    """Frontend reports cheating signals (tab switch, copy-paste, etc.)."""
    data = request.get_json() or {}
    if _active_agent and _active_agent.cheating_detector:
        _active_agent.cheating_detector.add_frontend_signal(
            signal_type=data.get("type", "unknown"),
            details=data.get("details", {}),
        )
        return jsonify({"status": "recorded"})
    return jsonify({"status": "ignored"})


@flask_app.route("/api/voice", methods=["POST"])
def set_voice():
    data = request.get_json() or {}
    speaker = data.get("speaker", "p251")
    if _active_agent and _active_agent.output:
        from output_handler import set_speaker
        set_speaker(speaker)
    return jsonify({"status": "ok", "speaker": speaker})


def run_flask():
    flask_app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


# ════════════════════════════════════════════════════
# AI Interviewer Agent
# ════════════════════════════════════════════════════
class AIInterviewerAgent:
    def __init__(self):
        self.room:   rtc.Room | None          = None
        self.output: AudioOutputHandler | None = None

        # Core engines
        self.interview_engine    = InterviewEngine()
        self.confidence_analyzer = ConfidenceAnalyzer()
        self.cheating_detector   = CheatingDetector()
        self.scoring_engine      = ScoringEngine()
        self.brain               = InterviewBrain()

        self._last_interaction  = time.time()
        self._silence_reminders = 0
        self._ws_task: asyncio.Task | None = None
        self._response_start_time = 0

    def _on_barge_in(self):
        """Candidate interrupted — note it for confidence scoring."""
        print("\n  [Interview] Candidate interrupted agent speech")
        if self.output:
            self.output.interrupt()
        # Frequent interruption can indicate nervousness or assertiveness
        self.confidence_analyzer.record_event("interruption")

    async def _on_utterance(self, audio_bytes: bytes):
        """
        INTERVIEW PIPELINE:
          1. STT (transcribe candidate speech)
          2. Confidence Analysis (hesitation, filler words, speech rate)
          3. Cheating Detection (response timing, consistency)
          4. Interview State Machine (decide next action)
          5. LLM Generation (interviewer response)
          6. TTS → Audio Output
          7. Score Update
        """
        import numpy as np

        self._last_interaction  = time.time()
        self._silence_reminders = 0

        # ── 1. STT ──
        pcm_int16   = np.frombuffer(audio_bytes, dtype=np.int16)
        duration_ms = len(pcm_int16) / SAMPLE_RATE * 1000
        print(f"\n  [Pipeline] STT: transcribing {duration_ms:.0f}ms …")

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, transcribe_audio, pcm_int16, False)

        if not text or len(text.strip()) < 2:
            print("  [Pipeline] STT returned empty — skipping")
            return

        print(f"\n[Candidate] {text}")
        if self.output:
            await self.output._send_transcript("candidate", text)
            self.output.interrupt()  # Clear any queued audio

        # ── 2. Confidence Analysis ──
        response_time = time.time() - self._response_start_time if self._response_start_time else 0
        confidence_data = self.confidence_analyzer.analyze_utterance(
            text=text,
            audio_bytes=audio_bytes,
            duration_ms=duration_ms,
            response_time_sec=response_time,
        )
        print(f"  [Confidence] score={confidence_data['score']:.1f}/10, "
              f"filler_rate={confidence_data['filler_rate']:.2f}, "
              f"speech_rate={confidence_data['speech_rate']:.0f} wpm")

        # ── 3. Cheating Detection (voice-side) ──
        self.cheating_detector.analyze_response(
            text=text,
            response_time_sec=response_time,
            question_context=self.interview_engine.get_current_question(),
        )

        # ── 4. Interview State Machine ──
        action = self.interview_engine.process_answer(text, confidence_data)
        print(f"  [Interview] State={self.interview_engine.state.value}, "
              f"Action={action['type']}, Q={self.interview_engine.current_question_idx}")

        # ── 5. Generate Interviewer Response ──
        context = {
            "interview_state": self.interview_engine.state.value,
            "action": action,
            "candidate_name": self.interview_engine.config.candidate_name,
            "role": self.interview_engine.config.role,
            "question_number": self.interview_engine.current_question_idx,
            "total_questions": self.interview_engine.config.num_questions,
            "confidence_data": confidence_data,
            "previous_exchanges": self.interview_engine.get_recent_exchanges(n=2),
        }

        print("  [Pipeline] LLM: generating interviewer response …")
        full_reply = []

        async for sentence in generate_interview_response_stream(text, context):
            print(f"  [Interviewer] {sentence}")
            full_reply.append(sentence)
            if self.output:
                self.output.speak(sentence)

        combined_reply = " ".join(full_reply)

        # ── 6. Record Exchange ──
        self.interview_engine.record_exchange(text, combined_reply)
        if self.output:
            await self.output._send_transcript("interviewer", combined_reply)

        # Mark when we finish speaking so we can measure response time
        self._response_start_time = time.time()

        # ── 7. Check if interview is complete ──
        if self.interview_engine.is_complete():
            await asyncio.sleep(2)
            if self.output:
                self.output.speak("That concludes our interview. Thank you for your time. "
                                  "You'll receive a detailed feedback report shortly.")
            print("\n" + "=" * 60)
            print("  INTERVIEW COMPLETE — Generating Report")
            print("=" * 60)

    async def _on_track(self, track: rtc.Track, participant: rtc.RemoteParticipant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        handler = AudioInputHandler(
            on_utterance_ready=self._on_utterance,
            is_agent_speaking=lambda: (self.output is not None and self.output.is_speaking),
            on_barge_in=self._on_barge_in,
        )

        await asyncio.sleep(1.5)

        # Deliver opening greeting
        if self.output:
            name = self.interview_engine.config.candidate_name
            role = self.interview_engine.config.role
            greeting = (
                f"Hello {name}! Welcome to your interview for the {role} position. "
                f"I'll be conducting this interview today. We'll cover a mix of "
                f"behavioral and domain-specific questions. Please take your time "
                f"and answer honestly. Let's begin."
            )
            self.output.speak(greeting)
            self.interview_engine.start()
            self._response_start_time = time.time()

            # Ask first question after a brief pause
            await asyncio.sleep(1)
            first_q = self.interview_engine.get_next_question()
            if first_q:
                self.output.speak(first_q)

        await handler.process_track(track, participant)

    async def _silence_monitor(self):
        """Monitors for silence — in interviews, silence is meaningful."""
        silence_msgs = [
            "Take your time, but please try to share your thoughts.",
            "I understand this might be challenging. Would you like me to rephrase the question?",
            "Let's move on to the next question.",
        ]
        while True:
            await asyncio.sleep(5)
            if (time.time() - self._last_interaction >= SILENCE_TIMEOUT_SEC
                    and self.output and not self.output.is_speaking
                    and self._silence_reminders < MAX_SILENCE_REMINDERS):
                self._silence_reminders += 1
                n = self._silence_reminders
                self.confidence_analyzer.record_event("long_silence")
                print(f"[Interview] Silence reminder {n}/{MAX_SILENCE_REMINDERS}")
                self.output.speak(silence_msgs[min(n - 1, len(silence_msgs) - 1)])
                self._last_interaction = time.time()

    async def run(self):
        global _active_agent
        _active_agent = self

        self.room = rtc.Room()

        @self.room.on("track_subscribed")
        def on_track(track, publication, participant):
            asyncio.ensure_future(self._on_track(track, participant))

        @self.room.on("participant_connected")
        def on_join(p):
            print(f"[*] Candidate {p.identity} joined the interview room")

        @self.room.on("participant_disconnected")
        def on_leave(p):
            print(f"[*] {p.identity} left the interview")
            if self.output:
                self.output.interrupt()
            self.cheating_detector.add_frontend_signal("disconnect", {"identity": p.identity})

        print(f"[*] Connecting to {LIVEKIT_URL} …")
        agent_token = (
            api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity("ai-interviewer")
            .with_name("AI Interviewer")
            .with_grants(api.VideoGrants(room_join=True, room=ROOM_NAME))
            .to_jwt()
        )
        await self.room.connect(LIVEKIT_URL, agent_token)
        print(f"[*] Connected — room: {self.room.name}")

        audio_source = rtc.AudioSource(SAMPLE_RATE, 1)
        track        = rtc.LocalAudioTrack.create_audio_track("interviewer-voice", audio_source)
        opts         = rtc.TrackPublishOptions()
        opts.source  = rtc.TrackSource.SOURCE_MICROPHONE
        await self.room.local_participant.publish_track(track, opts)

        self.output = AudioOutputHandler(audio_source, self.room)
        self.output.on_done = lambda: setattr(self, '_last_interaction', time.time())
        print("[*] Audio output track published")

        for p in self.room.remote_participants.values():
            for pub in p.track_publications.values():
                if pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
                    asyncio.ensure_future(self._on_track(pub.track, p))

        asyncio.ensure_future(self._silence_monitor())

        ws_input = WSInputHandler(
            on_utterance_ready=self._on_utterance,
            is_agent_speaking=lambda: (self.output is not None and self.output.is_speaking),
            on_barge_in=self._on_barge_in,
        )
        self._ws_task = asyncio.ensure_future(ws_input.start())

        print("\n" + "=" * 60)
        print("  AI INTERVIEWER — RUNNING")
        print("=" * 60)
        print("  STT    : Whisper (local) + SarvamAI (Indian languages)")
        print("  LLM    : Groq (llama-3.3-70b) → Ollama (fallback)")
        print("  TTS    : SarvamAI Bulbul v2 → Coqui VITS (fallback)")
        print("  RAG    : ChromaDB (question bank + context)")
        print("  SCORE  : Confidence + Cheating + Adaptive Difficulty")
        print("  API    : http://localhost:5000")
        print("  WS     : ws://localhost:5001/audio")
        print("=" * 60 + "\n")

        await asyncio.Event().wait()


# ════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════
async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    print("[*] Interview API → http://localhost:5000\n")

    agent = AIInterviewerAgent()
    try:
        await agent.run()
    except KeyboardInterrupt:
        print("\n[*] Shutting down …")
    finally:
        if agent.room:
            await agent.room.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Goodbye!")
