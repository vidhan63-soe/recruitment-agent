"""
PROCESSING MODULE — AI Interviewer
====================================
STT:  Whisper (local, HuggingFace) + SarvamAI (Indian languages)
LLM:  Groq (llama-3.3-70b-versatile, FREE) → Ollama (fallback)
RAG:  ChromaDB for question bank & context

All services have free tiers:
  - Groq: Free tier, no credit card needed
  - SarvamAI: ₹1000 free credits on signup
  - Whisper: Runs locally via faster-whisper
  - ChromaDB: Fully local
"""

import time
import uuid
import os
import re
import json
import numpy as np
import asyncio
from typing import Optional, AsyncGenerator

# ── Config ──────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 16000
WHISPER_MODEL = "small.en"
WHISPER_LANG  = "en"

import torch as _torch
WHISPER_DEVICE = "cuda" if _torch.cuda.is_available() else "cpu"

# Groq (FREE tier — llama-3.3-70b-versatile)
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"
GROQ_BASE_URL  = "https://api.groq.com/openai/v1"

# Ollama (local fallback)
OLLAMA_MODEL    = "llama3.2:3b"
OLLAMA_BASE_URL = "http://localhost:11434"

# SarvamAI (Indian language support)
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

USE_GROQ = bool(GROQ_API_KEY)


# ════════════════════════════════════════════════════
# 1. Load Whisper STT
# ════════════════════════════════════════════════════
print("[Processing] Loading faster-whisper STT …")
from faster_whisper import WhisperModel

whisper_model = WhisperModel(
    WHISPER_MODEL,
    device=WHISPER_DEVICE,
    compute_type="float16" if WHISPER_DEVICE == "cuda" else "int8",
    num_workers=2,
)
print(f"  ✓ Whisper '{WHISPER_MODEL}' on {WHISPER_DEVICE}")


# ════════════════════════════════════════════════════
# 2. ChromaDB RAG
# ════════════════════════════════════════════════════
print("[Processing] Setting up ChromaDB …")
import chromadb
from chromadb.utils import embedding_functions

_chroma_client = chromadb.Client()
_embedding_fn  = embedding_functions.DefaultEmbeddingFunction()

interview_collection = _chroma_client.get_or_create_collection(
    "interview_context", embedding_function=_embedding_fn
)
print("  ✓ ChromaDB ready")


# ════════════════════════════════════════════════════
# 3. LLM Setup (Groq primary, Ollama fallback)
# ════════════════════════════════════════════════════
if USE_GROQ:
    print(f"[Processing] Using Groq API ({GROQ_MODEL}) — FREE tier")
    try:
        from groq import AsyncGroq
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
        print(f"  ✓ Groq client initialized")
    except ImportError:
        print("  ⚠ groq package not installed. Run: pip install groq")
        USE_GROQ = False
else:
    print("[Processing] No GROQ_API_KEY — using Ollama only")

# Ollama fallback
print("[Processing] Connecting to Ollama (fallback) …")
import ollama
from ollama import AsyncClient as OllamaAsyncClient

try:
    _models = ollama.list()
    _names = [m.model for m in _models.models] if hasattr(_models, "models") else []
    _available = any(OLLAMA_MODEL in str(m) for m in _names)
    if _available:
        print(f"  ✓ Ollama: {OLLAMA_MODEL} available (fallback)")
        # Warm up
        ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            options={"num_predict": 1, "num_ctx": 1024},
            keep_alive=-1,
        )
    else:
        print(f"  ⚠ {OLLAMA_MODEL} not found. Run: ollama pull {OLLAMA_MODEL}")
except Exception as e:
    print(f"  ⚠ Ollama unreachable: {e}")

# SarvamAI STT (optional — for Indian languages)
_sarvam_client = None
if SARVAM_API_KEY:
    try:
        from sarvamai import SarvamAI
        _sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
        print(f"  ✓ SarvamAI STT ready (Indian language support)")
    except ImportError:
        print("  ⚠ sarvamai package not installed. Run: pip install sarvamai")

print("[Processing] All models ready.\n")


# ════════════════════════════════════════════════════
# STT (Speech-to-Text)
# ════════════════════════════════════════════════════
def transcribe_audio(pcm_int16: np.ndarray, is_barge_check: bool = False) -> str:
    """
    16kHz int16 PCM → transcript string.
    Uses local Whisper by default. Falls back to SarvamAI for Indian languages.
    """
    audio_f32 = pcm_int16.astype(np.float32) / 32768.0

    segments, info = whisper_model.transcribe(
        audio_f32,
        language=WHISPER_LANG,
        beam_size=1,
        vad_filter=True,
    )

    try:
        text = " ".join(seg.text for seg in segments).strip()
    except Exception as e:
        if not is_barge_check:
            print(f"  [STT] Error: {e}")
        return ""

    if not is_barge_check:
        print(f"  [STT] \"{text}\"  (lang={info.language} conf={info.language_probability:.2f})")

    return text


def transcribe_audio_sarvam(audio_bytes: bytes, language: str = "en-IN") -> str:
    """Use SarvamAI for Indian language STT (optional, uses free credits)."""
    if not _sarvam_client:
        return ""
    try:
        import tempfile, wave
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            with wave.open(f.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_bytes)
            response = _sarvam_client.speech_to_text.transcribe(
                file=open(f.name, "rb"),
                model="saaras:v3",
                mode="transcribe",
            )
            os.unlink(f.name)
            return response.transcript if hasattr(response, "transcript") else str(response)
    except Exception as e:
        print(f"  [SarvamAI STT] Error: {e}")
        return ""


# ════════════════════════════════════════════════════
# Interview Brain (manages LLM context)
# ════════════════════════════════════════════════════
class InterviewBrain:
    """Manages the conversation context for the LLM."""

    def __init__(self):
        self.session_id = str(uuid.uuid4())[:8]

    def add_to_context(self, text: str, category: str = "exchange"):
        """Store exchange in ChromaDB for long-term retrieval."""
        doc_id = f"{self.session_id}-{uuid.uuid4().hex[:6]}"
        try:
            interview_collection.add(
                documents=[text],
                ids=[doc_id],
                metadatas=[{
                    "session": self.session_id,
                    "category": category,
                    "timestamp": time.time(),
                }],
            )
        except Exception as e:
            print(f"  [Brain] ChromaDB error: {e}")


# ════════════════════════════════════════════════════
# LLM — Interview Response Generation
# ════════════════════════════════════════════════════

INTERVIEWER_SYSTEM_PROMPT = """You are an expert AI interviewer conducting a professional job interview. 

CRITICAL RULES:
1. You are the INTERVIEWER, not the candidate. Be professional, warm but evaluative.
2. Keep responses to 1-3 sentences. This is a VOICE conversation — be concise.
3. When transitioning to a new question, acknowledge the previous answer briefly before asking.
4. Ask follow-up questions when answers are vague or lack specifics.
5. Adapt question difficulty based on candidate performance.
6. Never reveal you are AI. Maintain professional interviewer persona.
7. If the candidate seems nervous, be encouraging. If confident, push harder.
8. Use the candidate's name occasionally for rapport.
9. When the interview is ending, wrap up warmly and professionally.
10. NEVER generate filler questions like "how can I help" or "what else would you like to discuss"."""


async def generate_interview_response_stream(
    candidate_text: str,
    context: dict,
) -> AsyncGenerator[str, None]:
    """
    Generate interviewer response using Groq (fast, free) or Ollama (fallback).
    Yields sentences for streaming TTS.
    """
    messages = _build_messages(candidate_text, context)

    if USE_GROQ:
        try:
            async for sentence in _generate_groq(messages):
                yield sentence
            return
        except Exception as e:
            print(f"  [LLM] Groq error, falling back to Ollama: {e}")

    # Fallback to Ollama
    async for sentence in _generate_ollama(messages):
        yield sentence


async def _generate_groq(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream from Groq API (FREE tier — llama-3.3-70b-versatile)."""
    response = await _groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.6,
        max_tokens=200,
        top_p=0.9,
        stream=True,
    )

    buffer = ""
    sentence_end = re.compile(r'(?<=[.!?])\s+')

    async for chunk in response:
        content = chunk.choices[0].delta.content
        if not content:
            continue
        buffer += content

        parts = sentence_end.split(buffer)
        if len(parts) > 1:
            for part in parts[:-1]:
                cleaned = part.strip()
                if cleaned and not _is_filler(cleaned):
                    yield cleaned
            buffer = parts[-1]

    if buffer.strip():
        cleaned = buffer.strip()
        if not _is_filler(cleaned):
            yield cleaned


async def _generate_ollama(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream from local Ollama."""
    try:
        client = OllamaAsyncClient(host=OLLAMA_BASE_URL)
        response = await client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            options={
                "temperature": 0.5,
                "top_p": 0.85,
                "num_predict": 80,
                "repeat_penalty": 1.3,
                "num_ctx": 2048,
            },
            stream=True,
            keep_alive=-1,
        )

        buffer = ""
        sentence_end = re.compile(r'(?<=[.!?])\s+')

        async for chunk in response:
            content = chunk['message']['content']
            buffer += content

            parts = sentence_end.split(buffer)
            if len(parts) > 1:
                for part in parts[:-1]:
                    cleaned = part.strip()
                    if cleaned and not _is_filler(cleaned):
                        yield cleaned
                buffer = parts[-1]

        if buffer.strip():
            cleaned = buffer.strip()
            if not _is_filler(cleaned):
                yield cleaned

    except Exception as e:
        print(f"  [LLM] Ollama error: {e}")
        yield "I appreciate your answer. Let me ask you another question."


def _build_messages(candidate_text: str, context: dict) -> list[dict]:
    """Build the message list for the LLM."""
    messages = [{"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT}]

    # Add interview context
    action = context.get("action", {})
    state = context.get("interview_state", "intro")
    role = context.get("role", "the position")
    name = context.get("candidate_name", "Candidate")
    q_num = context.get("question_number", 1)
    total = context.get("total_questions", 8)
    conf = context.get("confidence_data", {})

    context_prompt = f"""INTERVIEW CONTEXT:
- Candidate: {name}
- Role: {role}
- Current phase: {state}
- Question {q_num} of {total}
- Candidate confidence level: {conf.get('score', 5)}/10
- Action needed: {action.get('type', 'next_question')}"""

    if action.get("type") == "followup":
        context_prompt += f"\n- Follow-up reason: {action.get('reason', '')}"
        context_prompt += f"\n- Hint: {action.get('hint', '')}"
    elif action.get("type") == "next_question":
        context_prompt += f"\n- Next question to ask: {action.get('question', '')}"
    elif action.get("type") == "complete":
        context_prompt += "\n- Interview is COMPLETE. Wrap up professionally."

    messages.append({"role": "system", "content": context_prompt})

    # Add recent conversation history
    for exchange in context.get("previous_exchanges", []):
        if exchange.get("candidate"):
            messages.append({"role": "user", "content": exchange["candidate"]})
        if exchange.get("interviewer"):
            messages.append({"role": "assistant", "content": exchange["interviewer"]})

    # Current candidate answer
    messages.append({"role": "user", "content": candidate_text})

    return messages


def _is_filler(text: str) -> bool:
    """Filter out LLM filler patterns."""
    lower = text.lower().strip()
    filler_patterns = [
        "how else may i assist", "how else can i assist",
        "how can i assist you", "how may i assist you",
        "what else can i help", "is there anything else",
        "let me know how", "let me know if there",
    ]
    return any(p in lower for p in filler_patterns)


# ════════════════════════════════════════════════════
# Candidate Info Extraction
# ════════════════════════════════════════════════════
def extract_candidate_info(text: str) -> list[str]:
    """Extract candidate info from their responses."""
    info = []
    lower = text.lower()

    for phrase in ["my name is", "i'm called", "call me"]:
        if phrase in lower:
            idx = lower.index(phrase) + len(phrase)
            rest = text[idx:].strip().split()
            name = rest[0] if rest else None
            if name and len(name) > 1 and name.lower() not in ("not", "the", "a"):
                info.append(f"Candidate name: {name}")

    for phrase in ["i have", "i've got", "i've been"]:
        if phrase in lower and "year" in lower:
            info.append(text[lower.index(phrase):].strip()[:100])

    return info
