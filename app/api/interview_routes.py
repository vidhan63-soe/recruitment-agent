"""
Interview Agent Routes — all paths match what the HTML calls as relative URLs.
Included in FastAPI with NO prefix (paths already contain /api/...).

Routes the HTML calls:
  GET  /api/interview-session/{token}   ← auto-config on page load
  POST /api/interview/start             ← configure interview
  GET  /api/interview/status            ← poll status
  GET  /api/interview/report            ← final report
  POST /api/cheating/report             ← frontend signals
  POST /api/interview/checkin           ← save candidate notes to DB
  WS   /ws/audio                        ← raw PCM audio stream
"""

"""
Interview Agent Routes — all paths match what the HTML calls as relative URLs.
Included in FastAPI with NO prefix (paths already contain /api/...).

Routes the HTML calls:
  GET  /api/interview-session/{token}   ← auto-config on page load
  POST /api/interview/start             ← configure interview
  POST /api/interview/ai-respond        ← AI transition between questions (browser voice)
  GET  /api/interview/status            ← poll status
  GET  /api/interview/report            ← final report
  POST /api/cheating/report             ← frontend signals
  POST /api/interview/checkin           ← save candidate notes to DB
  WS   /ws/audio                        ← raw PCM audio stream
"""

import re
import time
import asyncio
import sqlite3
import json
import os
from pathlib import Path

import aiohttp
from datetime import datetime
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from loguru import logger
from app.core.config import get_settings

router = APIRouter()

DB_PATH = Path(__file__).parent.parent.parent / "recruitment.db"

# Global reference to the running AIInterviewerAgent — set from main.py
_interview_agent = None


def set_interview_agent(agent):
    global _interview_agent
    _interview_agent = agent


# ── DB helpers (sync, for routes called from Flask-style handlers) ──

def _db_get_setting(key: str, default: str = "") -> str:
    """Fetch a settings key-value (sync)."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def _db_get_session_jd(recruitment_session_id: str) -> dict:
    """Fetch jd_text and title from the parent recruitment session (sync)."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT jd_text, title FROM sessions WHERE id = ?", (recruitment_session_id,)
        ).fetchone()
        conn.close()
        if row:
            return {"jd_text": row["jd_text"] or "", "title": row["title"] or ""}
    except Exception as e:
        logger.warning(f"DB session JD lookup failed: {e}")
    return {"jd_text": "", "title": ""}


def _db_get_interview_by_token(token: str) -> dict | None:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM interview_sessions WHERE token = ?", (token,)
        ).fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["question_config"] = json.loads(d.get("question_config", "{}"))
            return d
        return None
    except Exception as e:
        logger.warning(f"DB interview lookup failed: {e}")
        return None


def _db_update_interview(token: str, **kwargs):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [token]
        conn.execute(f"UPDATE interview_sessions SET {sets} WHERE token = ?", vals)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"DB interview update failed: {e}")


# ══════════════════════════════════════════════════
# Candidate-Facing Routes
# ══════════════════════════════════════════════════

@router.get("/api/interview-session/{token}")
async def get_interview_session(token: str):
    """
    Called by the interview page on load.
    Returns candidate info and question config for auto-fill.
    """
    data = _db_get_interview_by_token(token)
    if not data:
        return JSONResponse({"error": "Invalid or expired interview link"}, status_code=404)

    cfg = data.get("question_config", {})
    return {
        "candidate_name": data.get("candidate_name", cfg.get("candidate_name", "")),
        "email": cfg.get("email", ""),
        "role": cfg.get("role", ""),
        "status": data.get("status", "pending"),
        "question_config": cfg,
    }


@router.post("/api/interview/checkin")
async def candidate_checkin(request: Request):
    """
    Candidate submits notes/corrections before the interview starts.
    Saves to interview_sessions.candidate_notes in DB.
    Also marks the session as active.
    """
    data = await request.json()
    token = data.get("token", "")
    notes = data.get("notes", "").strip()

    if not token:
        return JSONResponse({"error": "Token required"}, status_code=400)

    interview = _db_get_interview_by_token(token)
    if not interview:
        return JSONResponse({"error": "Invalid token"}, status_code=404)

    # Store notes inside question_config JSON (no schema change needed)
    cfg = interview.get("question_config", {})
    cfg["candidate_notes"] = notes
    _db_update_interview(
        token,
        question_config=json.dumps(cfg),
        status="active",
    )
    logger.info(f"Candidate checked in | token={token[:8]}… | notes={len(notes)} chars")
    return {"status": "ok", "message": "Notes saved"}


# ══════════════════════════════════════════════════
# AI Response Helper (browser-native voice interview)
# ══════════════════════════════════════════════════

# Male speakers available in Sarvam TTS bulbul:v2: abhilash (male), anushka (female)
_SARVAM_MALE_SPEAKER = "abhilash"

# Simple, varied, encouraging transition lines — no AI call, no answer analysis
_TRANSITION_PHRASES = [
    "Got it, thank you for sharing that.",
    "Appreciate you walking me through that.",
    "Noted — let's keep going.",
    "Thanks, that gives me a good picture.",
    "Alright, moving on.",
    "Thank you, that's helpful.",
    "Good, let's continue.",
    "Understood — next one coming up.",
    "Thanks for that, you're doing well.",
    "Okay, great — let's move forward.",
]

_ENCOURAGEMENT_PHRASES = [
    "No worries at all — just share whatever comes to mind, even a partial thought is perfectly fine.",
    "That's okay — take a breath and tell me anything related, there are no wrong answers here.",
    "Don't stress about it — even a rough idea or a past experience that connects works great.",
    "Completely fine — just speak freely, whatever you know is good enough.",
]


def _pick_transition(idx: int, answer: str) -> str:
    """Pick a scripted transition. If answer is very short, use encouragement instead."""
    confusion_signals = [
        "i don't know", "i dont know", "not sure", "no idea",
        "can't answer", "cannot answer", "i'm not sure", "i am not sure",
        "never done", "no experience", "not familiar", "drawing a blank",
        "only know this much", "thats all i know", "that's all i know", "i only know",
    ]
    lower = answer.lower().strip()
    words = len(lower.split())
    if words < 5 or any(sig in lower for sig in confusion_signals):
        return _ENCOURAGEMENT_PHRASES[idx % len(_ENCOURAGEMENT_PHRASES)]
    return _TRANSITION_PHRASES[idx % len(_TRANSITION_PHRASES)]


async def _generate_ai_transition(
    question: str, answer: str, idx: int,
    total: int, candidate_name: str, role: str,
) -> str:
    """Return a short, scripted transition phrase — no LLM call to avoid reasoning leakage."""
    return _pick_transition(idx, answer)


@router.post("/api/interview/ai-respond")
async def interview_ai_respond(request: Request):
    """
    Called by the browser interview after each candidate answer.
    Returns a short AI transition phrase to speak before the next question.
    """
    data = await request.json()
    response = await _generate_ai_transition(
        question=data.get("question", ""),
        answer=data.get("answer", ""),
        idx=int(data.get("question_idx", 0)),
        total=int(data.get("total_questions", 8)),
        candidate_name=data.get("candidate_name", "Candidate"),
        role=data.get("role", "this position"),
    )
    return {"response": response}


# ══════════════════════════════════════════════════
# Interview Engine Routes (called by HTML during interview)
# ══════════════════════════════════════════════════

@router.post("/api/interview/start")
async def interview_start(request: Request):
    """Configure the running interview agent for this candidate session."""
    data = await request.json()
    agent = _interview_agent

    if agent and agent.interview_engine:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "interview_agent"))
            from interview_engine import InterviewConfig

            config = InterviewConfig(
                role=data.get("role", "Software Engineer"),
                experience_level=data.get("experience_level", "mid"),
                domain=data.get("domain", "general"),
                candidate_name=data.get("candidate_name", "Candidate"),
                language=data.get("language", "en"),
                num_questions=int(data.get("num_questions", 8)),
                difficulty=data.get("difficulty", "adaptive"),
            )
            agent.interview_engine.configure(config)
            agent.confidence_analyzer.reset()
            agent.cheating_detector.reset()
            logger.info(f"Interview started: {config.candidate_name} | {config.role}")
            return {"status": "configured", "config": config.to_dict()}
        except Exception as e:
            logger.warning(f"Interview configure error: {e}")
            # Return configured so UI proceeds even if agent config fails
            return {"status": "configured"}

    return {"status": "agent_not_ready"}


@router.get("/api/interview/status")
async def interview_status():
    """Return current interview state, scores, and live transcript."""
    agent = _interview_agent
    if agent and agent.interview_engine:
        engine = agent.interview_engine
        return {
            "state": engine.state.value,
            "current_question": engine.current_question_idx,
            "total_questions": engine.config.num_questions,
            "elapsed_seconds": int(time.time() - engine.start_time) if engine.start_time else 0,
            "confidence_scores": agent.confidence_analyzer.get_summary(),
            "cheating_flags": agent.cheating_detector.get_flags(),
            "transcript": engine.get_transcript(),
        }
    return {"state": "not_started"}


@router.get("/api/interview/report")
async def interview_report():
    """Generate and return the final scored interview report."""
    agent = _interview_agent
    if agent and agent.scoring_engine:
        try:
            report = agent.scoring_engine.generate_report(
                interview_engine=agent.interview_engine,
                confidence_analyzer=agent.confidence_analyzer,
                cheating_detector=agent.cheating_detector,
            )
            return report
        except Exception as e:
            logger.warning(f"Report generation error: {e}")
    return JSONResponse({"error": "No interview data available yet"}, status_code=404)


@router.post("/api/cheating/report")
async def cheating_report(request: Request):
    """Accept frontend cheating signals: tab switch, copy, paste, DevTools, etc."""
    data = await request.json()
    agent = _interview_agent
    if agent and agent.cheating_detector:
        agent.cheating_detector.add_frontend_signal(
            signal_type=data.get("type", "unknown"),
            details=data.get("details", {}),
        )
    return {"status": "recorded"}


@router.post("/api/voice")
async def set_voice(request: Request):
    """Change the TTS speaker voice."""
    data = await request.json()
    speaker = data.get("speaker", "p251")
    agent = _interview_agent
    if agent and agent.output:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "interview_agent"))
            from output_handler import set_speaker
            set_speaker(speaker)
        except Exception:
            pass
    return {"status": "ok", "speaker": speaker}


@router.get("/api/token")
async def get_livekit_token(
    identity: str = "",
    room: str = "interview",
    token: str = "",
):
    """Generate a LiveKit access token, optionally validating an interview session token."""
    import os

    identity = identity or f"candidate-{int(time.time())}"
    interview_config = None

    if token:
        interview_data = _db_get_interview_by_token(token)
        if interview_data:
            interview_config = interview_data.get("question_config", {})
            candidate_name = interview_config.get("candidate_name", "")
            if candidate_name:
                identity = candidate_name.replace(" ", "-").lower()
            _db_update_interview(token, status="active")
            logger.info(f"LiveKit token issued for: {candidate_name or identity}")

    try:
        from livekit import api as lk_api
        LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://voice-4jhzmt71.livekit.cloud")
        LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "APIMwJJEKW5zdT3")
        LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "n5HvVm04pDoquZc8DHOhMG0b5lm1PbFEUYXRnOb6TcK")
        lk_token = (
            lk_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(identity)
            .with_grants(lk_api.VideoGrants(room_join=True, room=room))
        )
        return {
            "token": lk_token.to_jwt(), "url": LIVEKIT_URL,
            "room": room, "identity": identity,
            "interview_config": interview_config,
        }
    except ImportError:
        return {
            "token": "", "url": "", "room": room,
            "identity": identity, "interview_config": interview_config,
            "error": "LiveKit not installed",
        }


# ══════════════════════════════════════════════════
# WebSocket Audio
# ══════════════════════════════════════════════════

@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    """
    Raw PCM audio from the browser mic → interview agent pipeline.
    The HTML connects to: ws://localhost:8000/ws/audio
    Uses energy-based VAD to detect speech and call the agent's on_utterance.
    """
    try:
        import numpy as np
    except ImportError:
        await websocket.accept()
        await websocket.close(code=1011, reason="numpy not available")
        return

    await websocket.accept()
    agent = _interview_agent

    if not agent:
        await websocket.close(code=1011, reason="Interview agent not ready")
        return

    SAMPLE_RATE = 16000
    RMS_THRESHOLD = 300          # int16 RMS — tune if too sensitive
    MIN_SPEECH_BYTES = SAMPLE_RATE * 2 * 1    # 1 s minimum utterance
    MAX_BUFFER_BYTES = SAMPLE_RATE * 2 * 10   # 10 s max before forced flush
    SILENCE_CHUNKS_NEEDED = 10   # ~2 s of silence at 4096-sample chunks

    buffer = bytearray()
    silence_count = 0
    in_speech = False

    logger.info("[WS] Audio connection established")

    try:
        while True:
            data = await websocket.receive_bytes()
            samples = np.frombuffer(data, dtype=np.int16)
            rms = int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
            is_speech = rms > RMS_THRESHOLD

            if is_speech:
                buffer.extend(data)
                silence_count = 0
                in_speech = True
            elif in_speech:
                buffer.extend(data)
                silence_count += 1

                flush = (
                    silence_count >= SILENCE_CHUNKS_NEEDED
                    or len(buffer) >= MAX_BUFFER_BYTES
                )
                if flush and len(buffer) >= MIN_SPEECH_BYTES:
                    chunk = bytes(buffer)
                    if not (agent.output and agent.output.is_speaking):
                        asyncio.ensure_future(agent._on_utterance(chunk))
                    buffer = bytearray()
                    silence_count = 0
                    in_speech = False

    except WebSocketDisconnect:
        logger.info("[WS] Audio disconnected")
    except Exception as e:
        logger.error(f"[WS] Audio error: {e}")


# ══════════════════════════════════════════════════
# Report Submission (candidate → backend → recruiter)
# ══════════════════════════════════════════════════

AUDIO_DIR    = Path(__file__).parent.parent.parent / "uploads" / "audio"
VIDEO_DIR    = Path(__file__).parent.parent.parent / "uploads" / "video"
SNAPSHOT_DIR = Path(__file__).parent.parent.parent / "uploads" / "snapshots"


# ── TTS endpoint — Sarvam primary, Edge TTS secondary ───────────────────────────

@router.post("/api/interview/tts")
async def text_to_speech(request: Request):
    """
    Two interviewer personas:
      • persona="rahul"  → Sarvam bulbul:v2 / abhilash  (Indian-English)
      • persona="alex"   → Edge TTS en-US-GuyNeural      (American-English)
    Each falls back to the other if its primary service is unavailable.
    Returns { audio_base64, format, voice, persona }.
    """
    import base64
    body = await request.json()
    text = (body.get("text") or "").strip()[:600]
    persona = (body.get("persona") or "rahul").lower()
    settings = get_settings()

    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)

    async def try_sarvam() -> dict | None:
        sarvam_key = settings.SARVAM_API_KEY
        if not sarvam_key:
            return None
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    "https://api.sarvam.ai/text-to-speech",
                    headers={"api-subscription-key": sarvam_key, "Content-Type": "application/json"},
                    json={
                        "inputs": [text],
                        "target_language_code": "en-IN",
                        "speaker": _SARVAM_MALE_SPEAKER,   # abhilash
                        "model": "bulbul:v2",
                        "pitch": 0, "pace": 1.0, "loudness": 1.5,
                        "speech_sample_rate": 22050,
                        "enable_preprocessing": True,
                    },
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        audios = data.get("audios", [])
                        if audios:
                            return {"audio_base64": audios[0], "format": "wav", "voice": "rahul"}
                    else:
                        logger.warning(f"Sarvam TTS HTTP {resp.status}: {(await resp.text())[:120]}")
        except Exception as e:
            logger.warning(f"Sarvam TTS (Rahul) failed: {e}")
        return None

    async def try_edge() -> dict | None:
        edge_voice = settings.EDGE_TTS_VOICE  # en-US-GuyNeural
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice=edge_voice)
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            if audio_data:
                return {
                    "audio_base64": base64.b64encode(audio_data).decode(),
                    "format": "mp3",
                    "voice": "alex",
                }
        except Exception as e:
            logger.warning(f"Edge TTS (Alex) failed: {e}")
        return None

    # Route by persona — try preferred first, then fall back to the other
    if persona == "alex":
        result = await try_edge() or await try_sarvam()
    else:  # rahul (default)
        result = await try_sarvam() or await try_edge()

    if result:
        result["persona"] = persona
        return result

    return JSONResponse({"error": "TTS unavailable"}, status_code=503)


# ── Snapshot endpoints ─────────────────────────────────────────────────────────

@router.post("/api/interview-session/{token}/snapshot")
async def upload_snapshot(token: str, request: Request):
    """Save a JPEG snapshot captured from the candidate's camera on a cheating event."""
    body = await request.body()
    if not body:
        return JSONResponse({"error": "Empty snapshot"}, status_code=400)
    reason = request.query_params.get("reason", "periodic")
    snap_dir = SNAPSHOT_DIR / token
    snap_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:20]
    snap_path = snap_dir / f"{timestamp}_{reason[:20]}.jpg"
    snap_path.write_bytes(body)
    logger.info(f"Snapshot ({len(body)//1024} KB) | reason={reason} | token={token[:8]}…")
    return {"status": "saved", "file": snap_path.name}


@router.get("/api/interview-session/{token}/snapshots")
async def list_snapshots(token: str):
    """List all snapshot filenames for an interview."""
    snap_dir = SNAPSHOT_DIR / token
    if not snap_dir.exists():
        return {"snapshots": [], "count": 0}
    files = sorted(snap_dir.glob("*.jpg"))
    return {
        "count": len(files),
        "snapshots": [f"/api/interview-session/{token}/snapshot/{f.name}" for f in files],
    }


@router.get("/api/interview-session/{token}/snapshot/{filename}")
async def get_snapshot(token: str, filename: str):
    """Serve a snapshot image."""
    snap_file = SNAPSHOT_DIR / token / filename
    if not snap_file.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(str(snap_file), media_type="image/jpeg")


# ── Reset / allow retake ───────────────────────────────────────────────────────

@router.post("/api/interview-session/{token}/reset")
async def reset_interview_session(token: str):
    """
    Reset a completed interview so the candidate can retake with the same link.
    Clears the report, resets status to 'pending', removes all snapshots.
    Recruiter-only action.
    """
    interview = _db_get_interview_by_token(token)
    if not interview:
        return JSONResponse({"error": "Interview not found"}, status_code=404)
    _db_update_interview(token, status="pending", report="{}", completed_at=None)
    snap_dir = SNAPSHOT_DIR / token
    if snap_dir.exists():
        import shutil
        shutil.rmtree(str(snap_dir), ignore_errors=True)
    logger.info(f"Interview reset for retake | token={token[:8]}…")
    return {"status": "reset", "token": token}


@router.post("/api/interview-session/{token}/submit-report")
async def submit_interview_report(token: str, request: Request):
    """
    Called by the candidate's browser after the interview ends.
    Scores the transcript with LLM, enriches the report, then stores it.
    """
    data = await request.json()
    report = data.get("report", {})
    transcript = report.get("transcript", [])

    # ── LLM scoring ──────────────────────────────────────────────────────
    try:
        from app.agents.interview_agent import InterviewAgent
        agent = InterviewAgent()

        # Fetch session questions + JD for evaluation context
        interview = _db_get_interview_by_token(token)
        questions_config = []
        jd_text = ""
        role = ""
        if interview:
            questions_config = interview.get("question_config", {}).get("questions", [])
            recruitment_session_id = interview.get("recruitment_session_id", "")
            if recruitment_session_id:
                session_info = _db_get_session_jd(recruitment_session_id)
                jd_text = session_info.get("jd_text", "")
                role = interview.get("question_config", {}).get("role", "") or session_info.get("title", "")

        provider = _db_get_setting("llm_provider", "auto")
        scores = await agent.score_transcript(transcript, questions_config, jd_text=jd_text, role=role, provider=provider)

        # Merge scores back into transcript
        enriched_transcript = []
        total_score = 0
        for i, item in enumerate(transcript):
            entry = dict(item)
            if i < len(scores):
                s = scores[i]
                entry["score"] = s.get("score", 0)
                entry["feedback"] = s.get("feedback", "")
                entry["key_points_hit"] = s.get("key_points_hit", [])
                entry["key_points_missed"] = s.get("key_points_missed", [])
                total_score += s.get("score", 0)
            enriched_transcript.append(entry)

        if enriched_transcript:
            avg = round(total_score / len(enriched_transcript), 1)
            report["transcript"] = enriched_transcript
            report["overall_score"] = avg
            # Override recommendation based on LLM score
            if avg >= 7.5:
                report["recommendation"] = "Strong Hire"
            elif avg >= 6.0:
                report["recommendation"] = "Hire"
            elif avg >= 4.5:
                report["recommendation"] = "Maybe"
            else:
                report["recommendation"] = "No Hire"

        logger.info(f"LLM-scored {len(scores)} answers | avg={report.get('overall_score')} | token={token[:8]}…")
    except Exception as e:
        logger.warning(f"LLM scoring failed, keeping word-count scores: {e}")

    report_json = json.dumps(report)
    _db_update_interview(
        token,
        report=report_json,
        status="completed",
        completed_at=datetime.utcnow().isoformat(),
    )
    logger.info(f"Interview report saved | token={token[:8]}…")
    return {"status": "saved", "overall_score": report.get("overall_score")}


@router.post("/api/interview-session/{token}/audio")
async def upload_interview_audio(token: str, request: Request):
    """
    Called by the candidate's browser with the raw WebM audio blob.
    Stores it on disk so the recruiter can play it back.
    """
    body = await request.body()
    if not body:
        return JSONResponse({"error": "Empty audio"}, status_code=400)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = AUDIO_DIR / f"{token}.webm"
    audio_path.write_bytes(body)
    _db_update_interview(token, audio_path=str(audio_path))
    logger.info(f"Audio saved ({len(body)//1024} KB) | token={token[:8]}…")
    return {"status": "saved", "size_kb": len(body) // 1024}


@router.get("/api/interview-session/{token}/audio")
async def get_interview_audio(token: str):
    """Serve the candidate's recorded audio to the recruiter."""
    data = _db_get_interview_by_token(token)
    if not data or not data.get("audio_path"):
        return JSONResponse({"error": "No audio recorded"}, status_code=404)
    audio_file = Path(data["audio_path"])
    if not audio_file.exists():
        return JSONResponse({"error": "Audio file not found"}, status_code=404)
    return FileResponse(str(audio_file), media_type="audio/webm")


@router.post("/api/interview-session/{token}/video")
async def upload_interview_video(token: str, request: Request):
    """
    Called by the candidate's browser with the raw WebM video+audio blob.
    Stores it on disk so the recruiter can review the video recording.
    """
    body = await request.body()
    if not body:
        return JSONResponse({"error": "Empty video"}, status_code=400)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    video_path = VIDEO_DIR / f"{token}.webm"
    video_path.write_bytes(body)
    _db_update_interview(token, video_path=str(video_path))
    logger.info(f"Video saved ({len(body) // 1024} KB) | token={token[:8]}…")
    return {"status": "saved", "size_kb": len(body) // 1024}


@router.get("/api/interview-session/{token}/video")
async def get_interview_video(token: str):
    """Serve the candidate's recorded video to the recruiter."""
    data = _db_get_interview_by_token(token)
    if not data or not data.get("video_path"):
        return JSONResponse({"error": "No video recorded"}, status_code=404)
    video_file = Path(data["video_path"])
    if not video_file.exists():
        return JSONResponse({"error": "Video file not found"}, status_code=404)
    return FileResponse(str(video_file), media_type="video/webm")


@router.get("/api/interview-session/{token}/report")
async def get_interview_report(token: str):
    """Return stored report for a given interview token (recruiter use)."""
    data = _db_get_interview_by_token(token)
    if not data:
        return JSONResponse({"error": "Interview not found"}, status_code=404)
    report = json.loads(data.get("report") or "{}")
    has_video = bool(data.get("video_path") and Path(data["video_path"]).exists())
    return {
        "token": token,
        "candidate_name": data.get("candidate_name", ""),
        "status": data.get("status", "pending"),
        "report": report,
        "has_audio": bool(data.get("audio_path") and Path(data["audio_path"]).exists()),
        "audio_url": f"/api/interview-session/{token}/audio",
        "has_video": has_video,
        "video_url": f"/api/interview-session/{token}/video" if has_video else None,
        "completed_at": data.get("completed_at"),
    }
