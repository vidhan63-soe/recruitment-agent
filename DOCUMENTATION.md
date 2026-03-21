# Recruitment Agent — Complete Project Documentation

> Use this file as your reference before making any changes. Every file, its purpose, what it depends on, and what it provides is listed here.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture at a Glance](#2-architecture-at-a-glance)
3. [Directory Structure](#3-directory-structure)
4. [Backend — `app/`](#4-backend--app)
   - 4.1 Entry Point
   - 4.2 Core Config & GPU
   - 4.3 Data Models
   - 4.4 Services
   - 4.5 API Routes
   - 4.6 Agents
5. [Frontend — `frontend/src/`](#5-frontend--frontendsrc)
   - 5.1 Pages
   - 5.2 API Client
   - 5.3 Components
6. [Interview Agent — `interview_agent/`](#6-interview-agent--interview_agent)
7. [Database Schema](#7-database-schema)
8. [Data Flow Diagrams](#8-data-flow-diagrams)
9. [Scoring System](#9-scoring-system)
10. [Environment Variables](#10-environment-variables)
11. [API Reference](#11-api-reference)
12. [Technology Choices](#12-technology-choices)
13. [How to Add a New Feature](#13-how-to-add-a-new-feature)

---

## 1. Project Overview

An **AI-powered recruitment pipeline** that:

1. Parses resumes (PDF/DOCX) and stores them as vector embeddings in ChromaDB
2. Matches candidates against a job description using semantic search + LLM scoring
3. Sends AI-generated interview links to shortlisted candidates
4. Conducts a browser-based voice interview (Web Speech API)
5. Scores the transcript with an LLM using JD context + recruiter-defined expected answers
6. Presents a recruiter dashboard with ranked candidates, reports, and audio playback

**Target hardware:** GTX 1650 Ti (4 GB VRAM) / RTX 3050 (6 GB VRAM) — designed to run locally without a cloud GPU.

---

## 2. Architecture at a Glance

```
RECRUITER BROWSER (Next.js :3000)
  │
  ├── /recruiter          → Recruiter dashboard (session mgmt, ranking, reports)
  └── /candidate/interview → Candidate interview page (voice I/O, questions)
         │
         └── API calls → FastAPI server (:8000)
                            │
                ┌───────────┼───────────────┐
                │           │               │
           /api/v1      /api/interview   /ws/audio
          (routes.py)  (interview_routes)  (WebSocket)
                │           │
                ▼           ▼
           SQLite DB    InterviewAgent
           (database.py)  (interview_agent.py)
                │           │
                ▼           ▼
          ChromaDB      Sarvam AI / Ollama
          (vectorstore/) (LLM scoring)
```

---

## 3. Directory Structure

```
recruitment-agent/
│
├── main.py                        ← FastAPI entry point, service init
├── requirements.txt               ← Python dependencies
├── .env                           ← All environment variables (edit this for config)
├── recruitment.db                 ← SQLite database (auto-created on first run)
├── vectorstore/                   ← ChromaDB data (auto-created)
├── uploads/audio/                 ← Candidate interview audio recordings
│
├── app/
│   ├── core/
│   │   ├── config.py              ← Settings (reads .env)
│   │   └── gpu.py                 ← GPU detection + VRAM logging
│   │
│   ├── models/
│   │   └── schemas.py             ← Pydantic models (API contracts)
│   │
│   ├── services/
│   │   ├── database.py            ← SQLite async CRUD (aiosqlite)
│   │   ├── resume_parser.py       ← PDF/DOCX → text → chunks
│   │   ├── embedding_service.py   ← SentenceTransformer wrapper
│   │   ├── vector_store.py        ← ChromaDB wrapper
│   │   ├── llm_scorer.py          ← Ollama LLM scoring
│   │   ├── sarvam_scorer.py       ← Sarvam AI cloud scoring
│   │   └── matching_engine.py     ← Full RAG pipeline orchestrator
│   │
│   ├── api/
│   │   ├── routes.py              ← Main recruitment API (1200+ lines)
│   │   └── interview_routes.py    ← Interview API + WebSocket
│   │
│   └── agents/
│       ├── __init__.py            ← Exports InterviewAgent, ResumeAgent
│       ├── interview_agent.py     ← Question generation + transcript scoring
│       └── resume_agent.py        ← Resume pipeline wrapper
│
├── interview_agent/               ← Standalone voice interview engine
│   ├── app.py                     ← Flask server (legacy, mostly superseded)
│   ├── interview_engine.py        ← Interview state machine
│   ├── confidence_analyzer.py     ← Confidence scoring
│   ├── cheating_detector.py       ← Cheating signal tracking
│   ├── scoring.py                 ← Final report generation
│   ├── input_handler.py           ← LiveKit audio input
│   ├── input_ws.py                ← WebSocket audio input
│   ├── output_handler.py          ← TTS + audio output
│   └── processing.py              ← STT/LLM/TTS pipeline
│
└── frontend/
    ├── package.json               ← Next.js 15 + React 19 + Tailwind 4
    ├── next.config.mjs            ← API proxy: /api/* → localhost:8000/api/*
    └── src/
        ├── app/
        │   ├── page.tsx           ← Root: redirects to /recruiter
        │   ├── layout.tsx         ← Root layout
        │   ├── recruiter/
        │   │   └── page.tsx       ← Full recruiter dashboard
        │   └── candidate/
        │       └── interview/
        │           └── page.tsx   ← Candidate interview page
        │
        ├── components/
        │   ├── FileBrowser.tsx    ← Directory/file picker
        │   ├── BulkActionModal.tsx← Bulk email/status actions
        │   ├── CandidateCard.tsx  ← Candidate info card
        │   ├── ResumePreview.tsx  ← Resume text preview panel
        │   └── StatusBar.tsx      ← System health indicator
        │
        └── lib/
            └── api.ts             ← Typed fetch wrappers for all endpoints
```

---

## 4. Backend — `app/`

---

### 4.1 Entry Point

#### `main.py`

| Item | Detail |
|------|--------|
| **Purpose** | Starts FastAPI, loads all services, mounts routes |
| **Imports** | FastAPI, uvicorn, all service classes, both route modules |
| **Exports** | `app` (FastAPI instance) |

**What happens on startup (in order):**
1. Detect GPU → `get_device()` from `gpu.py`
2. Load embedding model → `EmbeddingService.load()`
3. Initialize ChromaDB → `VectorStoreService.initialize()`
4. Init SQLite → `database.init_db()`
5. Determine LLM provider (Sarvam → Ollama → keyword fallback) via health checks
6. Build `MatchingEngine` with all services
7. Inject services into routes via `routes.set_services()`
8. Optionally start legacy `InterviewAgent` (background task)

**Routes mounted:**
- `/api/v1` → `routes.router` (main recruitment API)
- No prefix → `interview_routes.router` (interview API)

**CORS:** All origins allowed (for local dev; tighten for production)

---

### 4.2 Core Config & GPU

#### `app/core/config.py`

| Item | Detail |
|------|--------|
| **Purpose** | Single source of truth for all settings |
| **Imports** | pydantic_settings.BaseSettings, pathlib.Path |
| **Exports** | `get_settings()` → cached `Settings` instance |

**Settings fields:**

```
HOST, PORT, DEBUG          ← Server
DEVICE                     ← "auto" | "cuda" | "cpu"
EMBEDDING_MODEL            ← "all-MiniLM-L6-v2"
OLLAMA_BASE_URL            ← "http://localhost:11434"
OLLAMA_MODEL               ← "mistral:7b-instruct-q4_K_M"
SARVAM_API_KEY             ← Set in .env
LLM_PROVIDER               ← "auto" | "sarvam" | "ollama" | "fallback"
CHROMA_PERSIST_DIR         ← "./vectorstore"
CHROMA_COLLECTION_NAME     ← "resumes"
CHUNK_SIZE, CHUNK_OVERLAP  ← 512, 50
MAX_RESUME_SIZE_MB         ← 10
TOP_K_CANDIDATES           ← 10
MIN_MATCH_SCORE            ← 0.35
```

**Usage:** `from app.core.config import get_settings; s = get_settings()`

---

#### `app/core/gpu.py`

| Item | Detail |
|------|--------|
| **Purpose** | Detect CUDA, return device string, log VRAM |
| **Imports** | torch |
| **Exports** | `get_device(preference)`, `log_gpu_usage(label)` |

- Warns if VRAM < 4 GB
- Falls back to CPU if CUDA unavailable
- Used in `EmbeddingService` and `main.py`

---

### 4.3 Data Models

#### `app/models/schemas.py`

| Item | Detail |
|------|--------|
| **Purpose** | All Pydantic models used in API contracts |
| **Imports** | pydantic.BaseModel |
| **Exports** | All classes below |

**Classes:**

| Class | Fields | Used By |
|-------|--------|---------|
| `ResumeChunk` | chunk_id, resume_id, text, chunk_index, metadata | vector_store, embedding |
| `ParsedResume` | resume_id, filename, candidate_name, email, phone, raw_text, sections, chunks | resume_parser → routes |
| `JobDescription` | jd_id, title, company, raw_text, required_skills, experience_years | matching |
| `CandidateScore` | resume_id, candidate_name, email, semantic_score, llm_score, final_score, matched_skills, missing_skills, summary, rank | MatchingEngine output |
| `MatchResult` | jd_id, jd_title, total_resumes, candidates, processed_at | /match endpoint |
| `UploadResponse` | resume_id, filename, candidate_name, status, chunk_count | /resumes/upload |
| `MatchRequest` | jd_text, jd_title, company, top_k, min_score | /match body |
| `HealthResponse` | status, gpu, embedding_model, llm_model, total_resumes, version | /health |

---

### 4.4 Services

#### `app/services/resume_parser.py`

| Item | Detail |
|------|--------|
| **Purpose** | Extract text from PDF/DOCX, identify sections, chunk for embeddings |
| **Imports** | pdfplumber, python-docx, re, uuid |
| **Exports** | `parse_resume(file_bytes, filename)` → dict |

**Pipeline:**
```
file_bytes
  → extract_text_from_pdf() or extract_text_from_docx()
  → extract_contact_info(text)   → {name, email, phone}
  → extract_sections(text)       → {education: ..., experience: ..., skills: ...}
  → chunk_text(text, 512, 50)    → list of overlapping chunks
  → returns ParsedResume dict
```

**Key functions:**

| Function | What it does |
|----------|-------------|
| `extract_text_from_pdf(bytes)` | pdfplumber page-by-page + table extraction |
| `extract_text_from_docx(bytes)` | python-docx paragraphs + tables |
| `extract_contact_info(text)` | Regex for email, phone; name from first non-empty line |
| `extract_sections(text)` | Regex matches section headers (Education, Experience, Skills, Projects, etc.) |
| `chunk_text(text, size, overlap)` | Splits at sentence boundaries, overlapping windows |
| `parse_resume(bytes, filename)` | Full pipeline, returns complete dict |

---

#### `app/services/embedding_service.py`

| Item | Detail |
|------|--------|
| **Purpose** | Load SentenceTransformer model, encode text → vectors |
| **Imports** | sentence_transformers.SentenceTransformer, torch |
| **Exports** | `EmbeddingService` class |

**Class methods:**

| Method | What it does |
|--------|-------------|
| `load()` | Loads model onto GPU/CPU; enables fp16 if CUDA to halve VRAM usage |
| `encode(texts, batch_size)` | Batch encoding → normalized float32 vectors (384 dims for MiniLM) |
| `encode_single(text)` | Encodes one string, returns list[float] |
| `unload()` | Calls `del model`, calls `torch.cuda.empty_cache()` |

**Model default:** `all-MiniLM-L6-v2` — 80 MB, 384-dim, fast, good quality for semantic search.

---

#### `app/services/vector_store.py`

| Item | Detail |
|------|--------|
| **Purpose** | Store and query resume chunk embeddings via ChromaDB |
| **Imports** | chromadb |
| **Exports** | `VectorStoreService` class |

**Key design decisions:**
- Uses **cosine distance** (collection metadata: `hnsw:space = cosine`)
- ChromaDB distance (0–2) converted → similarity score (1 − distance/2)
- Query returns 2×top_k chunks, then **aggregates per resume** with weighted top-3 scoring: `0.5×best + 0.3×second + 0.2×third`

**Methods:**

| Method | What it does |
|--------|-------------|
| `initialize()` | Creates/opens ChromaDB PersistentClient + collection |
| `add_resume_chunks(chunks, embeddings)` | Upserts into collection (resume_id + chunk_index as document IDs) |
| `query(embedding, top_k)` | Returns top_k resumes by weighted chunk similarity |
| `delete_resume(resume_id)` | Removes all chunks for a resume |
| `get_total_resumes()` | Counts unique resume IDs in collection |
| `reset()` | Drops and recreates collection (destructive!) |

---

#### `app/services/llm_scorer.py`

| Item | Detail |
|------|--------|
| **Purpose** | Score candidate against JD using local Ollama LLM |
| **Imports** | httpx (async HTTP), loguru |
| **Exports** | `LLMScorer` class |

**Scoring flow:**
1. Builds prompt: JD text + top 3 resume chunks + candidate name
2. POST to `{OLLAMA_BASE_URL}/api/generate` (60s timeout, temp=0.1 for consistency)
3. Parses JSON from response: `{llm_score, matched_skills, missing_skills, summary}`
4. Falls back to keyword matching if Ollama unavailable

**Fallback:** Extracts tech keywords from JD (Python, React, Docker, etc.), counts matches in resume text, score = matched/total.

---

#### `app/services/sarvam_scorer.py`

| Item | Detail |
|------|--------|
| **Purpose** | Score candidate using Sarvam AI cloud LLM (primary if API key is set) |
| **Imports** | httpx (async), loguru |
| **Exports** | `SarvamScorer` class |

**Same interface as LLMScorer** — drop-in replacement.

- Endpoint: `https://api.sarvam.ai/v1/chat/completions`
- Model: `sarvam-m` (24B multilingual, cheaper than GPT-4)
- Handles `</think>` tags from chain-of-thought mode
- Rate limit: 60 req/min (handles 429 gracefully)

---

#### `app/services/matching_engine.py`

| Item | Detail |
|------|--------|
| **Purpose** | Orchestrate full RAG matching pipeline |
| **Imports** | EmbeddingService, VectorStoreService, LLMScorer (or SarvamScorer) |
| **Exports** | `MatchingEngine` class |

**`match(jd_text, jd_title, top_k, min_score)` flow:**
```
1. embed JD text → query_vector
2. vector_store.query(query_vector, top_k×2) → semantic candidates
3. Filter: skip if semantic_score < min_score × 0.5
4. For each candidate:
   a. scorer.score_candidate(jd_text, chunks, name) → llm_score, skills, summary
   b. final_score = 0.4 × semantic + 0.6 × llm
5. Filter: final_score >= min_score
6. Sort descending, assign ranks, return top_k
```

**Scoring weights: 40% semantic + 60% LLM.** Change the multipliers here to rebalance.

---

#### `app/services/database.py`

| Item | Detail |
|------|--------|
| **Purpose** | All SQLite persistence — sessions, candidates, interviews, emails, questions |
| **Imports** | aiosqlite, json, datetime, loguru |
| **Exports** | All async functions listed below |

**Tables created by `init_db()`:**

| Table | Purpose |
|-------|---------|
| `sessions` | Recruitment sessions (title, JD text, status, scores, question bank) |
| `candidates` | Candidates per session (scores, skills, contact, status) |
| `resumes` | Resume metadata (name, email, path, sections) |
| `email_templates` | Email templates (name, subject, body, type) |
| `email_log` | Sent emails log |
| `interview_sessions` | Interview links (token, question config, status, report, audio path) |

**Migration:** `init_db()` also runs `ALTER TABLE` migrations (idempotent `try/except`) for columns added after initial schema: `session_questions`, `report`, `audio_path`.

**Key functions by category:**

*Sessions:*
- `create_session(id, title, jd_text, cv_dir, cutoff)` → creates row
- `get_session(id)` → dict or None
- `list_sessions()` → list of dicts
- `update_session(id, **kwargs)` → partial update
- `delete_session(id)` → also deletes associated candidates

*Candidates:*
- `save_candidates(session_id, candidates)` → bulk upsert
- `get_candidates(session_id, status_filter)` → list
- `update_candidate_status(session_id, resume_id, status)`

*Resumes:*
- `save_resume_meta(resume_id, name, email, phone, filename, path, sections, chunk_count)`
- `get_resume_meta(resume_id)` → dict

*Question Bank:*
- `get_session_questions(session_id)` → `list[QuestionItem]` (normalizes old string[] format)
- `save_session_questions(session_id, questions)` → upsert as JSON
- `_normalize_question(q)` → converts old `string` format to `{question, expected_answer, key_points}`

*Interviews:*
- `create_interview_session(id, recruitment_session_id, candidate_id, name, token, question_config, url)`
- `get_interview_session_by_token(token)` → dict with parsed question_config
- `get_interview_session_by_candidate(session_id, resume_id)` → dict
- `get_interview_sessions_for_recruitment(session_id)` → list
- `update_interview_session(token, **kwargs)` → partial update (status, report, audio_path, etc.)
- `get_interview_stats_for_recruitment(session_id)` → `{pending, active, completed, total}`

*Email:*
- `create_default_templates()` → inserts selection/rejection templates if empty
- `get_templates(type)` → list
- `log_email(session_id, resume_id, name, email_to, template, subject, status)`
- `get_email_log(session_id)` → list

---

### 4.5 API Routes

#### `app/api/routes.py` (~1200 lines)

| Item | Detail |
|------|--------|
| **Purpose** | All recruitment API endpoints (resumes, sessions, matching, interviews) |
| **Imports** | FastAPI, database, all schemas, config, InterviewAgent |
| **Mounted at** | `/api/v1` |

**Service injection:** `set_services(services_dict)` called from `main.py` at startup. Routes access services via `get_embedding_service()`, `get_vector_store()`, etc.

**Endpoint groups:**

| Group | Endpoints | What they do |
|-------|-----------|-------------|
| **Health** | GET `/health` | Returns system status, GPU info, resume count |
| **Resume Upload** | POST `/resumes/upload` | Parse + embed + store resumes (file upload) |
| **Resume Management** | GET/DELETE `/resumes`, DELETE `/resumes/{id}` | List and delete |
| **Directory Scan** | POST `/resumes/scan-directory` | Batch process a local folder |
| **File Browse** | POST `/browse`, POST `/read-file` | Filesystem navigation, read JD files |
| **Matching** | POST `/match` | Full RAG matching against JD |
| **Sessions** | POST `/sessions/start` | Full workflow: scan → match → save |
| **Sessions** | GET/DELETE `/sessions`, GET `/sessions/{id}` | CRUD |
| **Candidates** | GET `/sessions/{id}/candidates` | List with optional status filter |
| **Candidate Status** | POST `/sessions/{id}/candidates/{rid}/status` | Change status |
| **Resume Preview** | GET `/resume/{id}/preview` | Fetch text from file on disk |
| **Email** | GET `/templates`, POST `/sessions/{id}/bulk-action` | Templates + bulk email/status |
| **Email Log** | GET `/sessions/{id}/emails` | History |
| **Dashboard** | GET `/dashboard` | Aggregated stats across all sessions |
| **Cutoff** | POST `/sessions/{id}/update-cutoff` | Re-classify by new threshold |
| **Question Bank** | GET/POST `/sessions/{id}/questions` | Fetch or save questions |
| **Generate Questions** | POST `/sessions/{id}/questions/generate` | LLM generates + persists |
| **Preview Questions** | POST `/sessions/{id}/generate-questions` | LLM generates (no save) |
| **Single Interview** | POST `/sessions/{id}/candidates/{rid}/generate-interview` | Create token + URL |
| **Bulk Interview** | POST `/sessions/{id}/bulk-generate-interviews` | Create for multiple candidates |
| **Interview List** | GET `/sessions/{id}/interviews` | All interview sessions + stats |
| **Interview Token** | GET `/interview/{token}` | Config by token (used by interview agent) |
| **Interview Complete** | POST `/interview/{token}/complete` | Mark as done |
| **Interview Report** | GET `/sessions/{id}/candidates/{rid}/interview-report` | Recruiter view |
| **Score Answers** | POST `/sessions/{id}/candidates/{rid}/score-answers` | On-demand LLM scoring |

**`InterviewAgent` singleton:** Created at module level as `_interview_agent = _InterviewAgent()`. Used for question generation and answer scoring.

---

#### `app/api/interview_routes.py` (~570 lines)

| Item | Detail |
|------|--------|
| **Purpose** | Interview API: candidate-facing + recruiter report access |
| **Imports** | FastAPI, sqlite3 (sync), json, datetime, aiohttp, InterviewAgent |
| **Mounted at** | No prefix (routes already have `/api/...`) |

**Note:** Uses **sync `sqlite3`** (not aiosqlite) for compatibility with the WebSocket handler.

**DB helpers (sync):**
- `_db_get_session_jd(recruitment_session_id)` → `{jd_text, title}`
- `_db_get_interview_by_token(token)` → full interview row dict
- `_db_update_interview(token, **kwargs)` → partial UPDATE

**Endpoints:**

| Endpoint | Called By | What it does |
|----------|-----------|-------------|
| GET `/api/interview-session/{token}` | Candidate page on load | Returns config: name, role, questions, status |
| POST `/api/interview/checkin` | Candidate before interview | Saves notes, marks active |
| POST `/api/interview/ai-respond` | Candidate page after each answer | Returns AI transition phrase (Sarvam → scripted) |
| POST `/api/interview/start` | Legacy HTML interview | Configures old InterviewEngine |
| GET `/api/interview/status` | Legacy polling | Real-time state (old engine) |
| GET `/api/interview/report` | Legacy | Final report (old engine) |
| POST `/api/cheating/report` | Candidate page | Logs tab switch, copy, paste signals |
| GET `/api/token` | LiveKit flow | Generates WebRTC access token |
| WS `/ws/audio` | Browser mic | PCM audio → VAD → utterance → agent |
| **POST `/api/interview-session/{token}/submit-report`** | Candidate page at end | **LLM scores transcript, stores enriched report** |
| POST `/api/interview-session/{token}/audio` | Candidate page | Saves WebM audio to `uploads/audio/` |
| GET `/api/interview-session/{token}/audio` | Recruiter | Serves audio file (FileResponse) |
| GET `/api/interview-session/{token}/report` | Recruiter | Returns stored report + has_audio flag |

**`submit-report` flow (most important):**
```
1. Parse transcript from request body
2. _db_get_interview_by_token(token) → questions_config, recruitment_session_id
3. _db_get_session_jd(recruitment_session_id) → jd_text, role
4. InterviewAgent().score_transcript(transcript, questions_config, jd_text, role)
5. Merge scores into each transcript item (score, feedback, key_points_hit/missed)
6. Calculate overall_score = average of per-question scores
7. Set recommendation: ≥7.5→"Strong Hire", ≥6.0→"Hire", ≥4.5→"Maybe", <4.5→"No Hire"
8. Store enriched report JSON in DB, mark status="completed"
```

---

### 4.6 Agents

#### `app/agents/__init__.py`

Exports `InterviewAgent` and `ResumeAgent` for import elsewhere.

---

#### `app/agents/interview_agent.py`

| Item | Detail |
|------|--------|
| **Purpose** | LLM-powered question generation and transcript scoring |
| **Imports** | json, re, os, aiohttp, loguru |
| **Exports** | `InterviewAgent`, `QuestionItem`, `QuestionScore` |

**Types:**
```python
class QuestionItem(TypedDict):
    question: str
    expected_answer: str   # Recruiter-defined ideal answer (optional)
    key_points: list[str]  # Keywords LLM checks in candidate's answer

class QuestionScore(TypedDict):
    score: int             # 0-10
    feedback: str          # Specific actionable feedback
    key_points_hit: list[str]
    key_points_missed: list[str]
```

**`generate_questions(jd_text, role, n)` flow:**
```
Build prompt (requests JSON array of {question, expected_answer, key_points})
→ try Sarvam AI (40s timeout)
→ try Ollama (90s timeout)
→ return _fallback_questions(role, n)   ← 8 hardcoded generic questions
```

**`score_transcript(transcript, questions_config, jd_text, role)` flow:**
```
Build scoring prompt:
  - Includes JD text (first 2000 chars)
  - For each Q&A: question + expected_answer + key_points + candidate's answer
  - Strict rubric: score by content quality NOT length
  - Penalises off-topic/nonsensical answers (0-2)
→ try Sarvam AI
→ try Ollama
→ _fallback_score(): keyword overlap (key_points → expected_answer words → JD words)
   NOTE: never uses pure word count
```

**LLM helpers:**
- `_try_sarvam(prompt, max_tokens)` → reads `SARVAM_API_KEY` env var
- `_try_ollama(prompt, max_tokens)` → reads `OLLAMA_BASE_URL`, `OLLAMA_MODEL` env vars

---

#### `app/agents/resume_agent.py`

| Item | Detail |
|------|--------|
| **Purpose** | Thin wrapper around the resume processing pipeline |
| **Imports** | loguru, app.services.resume_parser |
| **Exports** | `ResumeAgent` class |

**Class:** `ResumeAgent(embedding_service, vector_store, matching_engine)`
- `parse_and_embed(file_bytes, filename)` → parsed dict
- `match_jd(jd_text, session_id, top_k)` → ranked candidates

Currently the routes access services directly; `ResumeAgent` is available for future refactoring.

---

## 5. Frontend — `frontend/src/`

---

### 5.1 Pages

#### `app/page.tsx`

Redirects `/` → `/recruiter`. Only 6 lines.

---

#### `app/recruiter/page.tsx` (~1300 lines)

| Item | Detail |
|------|--------|
| **Purpose** | Full recruiter dashboard |
| **Imports** | useState, useEffect, useRef, all api.ts functions, QuestionItem type, FileBrowser, BulkActionModal |
| **Route** | `/recruiter` |

**App phases (state machine):**

| Phase | What the recruiter sees |
|-------|------------------------|
| `dashboard` | List of all past recruitment sessions |
| `new_profile` | Form: CV directory picker + JD upload/type |
| `processing` | Animated log of ongoing session creation |
| `profile_view` | Session detail: ranked candidates table + side panel |

**Key state variables:**

```typescript
phase                  ← current UI phase
health                 ← system status from /health
dashboard              ← aggregated stats
sessions               ← all past sessions
candidates             ← current session candidates
currentSessionId       ← active session ID
currentTitle           ← active session title
activeCandidate        ← candidate selected for preview
previewTab             ← "resume" | "parsed" | "interview"
checkedIds             ← Set<string> for multi-select
interviewMap           ← {[resume_id]: InterviewSession}
sessionQuestions       ← QuestionItem[] from question bank
interviewReport        ← report data for selected candidate
```

**Main sub-components (all in same file):**

| Component | Props | Purpose |
|-----------|-------|---------|
| `SessionQuestionsPanel` | sessionId, questions, onSave, onClose | Modal to create/edit question bank with expected answers + key points |
| `InterviewSetupModal` | sessionId, targetCount, sessionQuestions, onGenerate | Modal to pick question source and generate interview links |
| `InterviewReportPanel` | interviewSession, report, loading | Side panel: score bar, recommendation, transcript with LLM feedback, audio player |
| `InterviewStatusBadge` | status | Colored badge: pending/in progress/completed |

**Question bank flow:**
```
Recruiter clicks "Question bank" button
  → SessionQuestionsPanel opens
  → "Generate from JD" → POST /sessions/{id}/questions/generate
  → Or type manually
  → Each question can be expanded to add expected_answer + key_points
  → Save → POST /sessions/{id}/questions (JSON body {questions: [...]})
  → sessionQuestions state updated
```

**Interview generation flow:**
```
Recruiter selects candidates → "Send interview" button
  → InterviewSetupModal opens (choose: session bank / auto-generate / custom)
  → Confirm → bulkGenerateInterviews() or generateInterviewLink()
  → POST /sessions/{id}/bulk-generate-interviews?resume_ids=...
  → interview_url returned → recruiter copies + sends to candidate
```

---

#### `app/candidate/interview/page.tsx` (~900 lines)

| Item | Detail |
|------|--------|
| **Purpose** | Candidate-facing interview UI with voice I/O |
| **Imports** | useState, useEffect, useRef, useCallback, useSearchParams, Suspense |
| **Route** | `/candidate/interview?token={token}` |
| **Note** | Wrapped in `<Suspense>` because it uses `useSearchParams()` |

**Types:**
```typescript
type Phase = "loading" | "setup" | "interview" | "report"
type QAItem = {
  question: string; answer: string; words: number;
  score?: number; feedback?: string;
  key_points_hit?: string[]; key_points_missed?: string[];
}
type SessionData = {
  candidate_name, email, role, questions, num_questions, difficulty
}
```

**App phases:**

| Phase | What candidate sees |
|-------|-------------------|
| `loading` | Spinner while fetching config |
| `setup` | Profile confirmation + notes input |
| `interview` | Question display + mic status + current answer text |
| `report` | ✅ "Interview Submitted" thank-you screen (NO scores shown) |

**Key refs (persist across renders without re-render):**
- `recognitionRef` — Web Speech API SpeechRecognition instance
- `mediaRecorderRef` — MediaRecorder for WebM audio capture
- `audioChunksRef` — Collected audio blobs
- `qaRef` — Array of QAItem objects built during interview
- `abortedRef` — Flag to stop interview loop

**Interview loop (`runInterview()`):**
```
For each question (i = 0 to n-1):
  1. setQuestionIdx(i)
  2. speak(question) via Web Speech API SpeechSynthesis
  3. await listenForAnswer() → SpeechRecognition → returns text
  4. POST /api/interview/ai-respond → transition phrase
  5. speak(transition)
  6. qaRef.current.push({question, answer, words})
  7. update gaugeOverall (running average)
End:
  → buildReport() → POST /api/interview-session/{token}/submit-report
  → (if audio recording) POST /api/interview-session/{token}/audio
  → setPhase("report")
```

**Tab switch handling:**
- `visibilitychange` event → `setTabWarning(true)` → yellow banner shown
- Simultaneously POSTs to `/api/cheating/report` with type "tab_switch"
- Recruiter sees this in the interview report's integrity flags

**Text fallback (no SpeechRecognition, e.g. Firefox):**
- Shows textarea for typing answers instead

---

### 5.2 API Client

#### `lib/api.ts`

| Item | Detail |
|------|--------|
| **Purpose** | All HTTP calls to the backend, fully typed |
| **Base URL** | `const API = "/api/v1"` (proxied by Next.js to `localhost:8000`) |
| **Exports** | All functions + types below |

**Types exported:**
```typescript
type QuestionItem = { question: string; expected_answer: string; key_points: string[] }
type QuestionScore = { score: number; feedback: string; key_points_hit: string[]; key_points_missed: string[] }
```

**Functions by group:**

| Function | HTTP | Endpoint | Returns |
|----------|------|----------|---------|
| `fetchHealth()` | GET | `/health` | HealthResponse |
| `scanDirectory(dir)` | POST | `/resumes/scan-directory` | scan results |
| `matchJD(jd, title, topK)` | POST | `/match` | MatchResult |
| `listResumes()` | GET | `/resumes` | resume list |
| `deleteAllResumes()` | DELETE | `/resumes` | — |
| `startSession(title, jd, dir, cutoff)` | POST | `/sessions/start` | session + candidates |
| `listSessions()` | GET | `/sessions` | session list |
| `getSession(id)` | GET | `/sessions/{id}` | session detail |
| `deleteSession(id)` | DELETE | `/sessions/{id}` | — |
| `changeCandidateStatus(sid, rid, status)` | POST | `/sessions/{sid}/candidates/{rid}/status` | — |
| `previewResume(rid)` | GET | `/resume/{rid}/preview` | text + meta |
| `getTemplates(type)` | GET | `/templates` | template list |
| `bulkAction(sid, action, ids, templateId, vars)` | POST | `/sessions/{sid}/bulk-action` | results |
| `updateCutoff(sid, cutoff)` | POST | `/sessions/{sid}/update-cutoff` | updated candidates |
| `getDashboard()` | GET | `/dashboard` | stats |
| `getSessionQuestions(sid)` | GET | `/sessions/{sid}/questions` | `{questions: QuestionItem[]}` |
| `generateAndSaveSessionQuestions(sid, role, n)` | POST | `/sessions/{sid}/questions/generate` | `{questions, count, saved}` |
| `saveSessionQuestions(sid, questions)` | POST | `/sessions/{sid}/questions` | — |
| `generateQuestionsFromJD(sid, role, n)` | POST | `/sessions/{sid}/generate-questions` | `{questions}` (no save) |
| `generateInterviewLink(sid, rid, opts)` | POST | `/sessions/{sid}/candidates/{rid}/generate-interview` | `{interview_url, token}` |
| `bulkGenerateInterviews(sid, rids, opts)` | POST | `/sessions/{sid}/bulk-generate-interviews` | results list |
| `getSessionInterviews(sid)` | GET | `/sessions/{sid}/interviews` | `{interviews, stats}` |
| `getCandidateInterviewReport(sid, rid)` | GET | `/sessions/{sid}/candidates/{rid}/interview-report` | report + audio |
| `submitInterviewReport(token, report)` | POST | `/api/interview-session/{token}/submit-report` | `{status, overall_score}` |
| `uploadInterviewAudio(token, blob)` | POST | `/api/interview-session/{token}/audio` | — |

**Error handling pattern:**
```typescript
const err = await res.json().catch(() => ({ detail: "Unknown error" }));
throw new Error(err.detail || `Error ${res.status}`);
```

---

### 5.3 Components

#### `components/FileBrowser.tsx`

| Props | Purpose |
|-------|---------|
| `isOpen, onClose, onSelect` | Modal file/folder picker |

- Navigates filesystem via `POST /api/v1/browse`
- Shows folders and files, filters by type
- Returns selected path to parent via `onSelect(path)`

---

#### `components/BulkActionModal.tsx`

| Props | Purpose |
|-------|---------|
| `sessionId, candidates, actionType, onClose, onDone` | Bulk operations modal |

- Actions: `send_email`, `change_status`
- For email: shows template selector + variable substitution preview
- Calls `bulkAction()` from api.ts

---

#### `components/CandidateCard.tsx`

| Props | Purpose |
|-------|---------|
| `candidate, onViewDetails, onStatusChange, isChecked, onCheck` | Single candidate row/card |

- Displays: rank, name, email, scores (semantic / LLM / final)
- Shows matched/missing skills as tags
- Status badge + action buttons

---

#### `components/ResumePreview.tsx`

| Props | Purpose |
|-------|---------|
| `candidate, resumeText, isLoading, meta` | Resume text side panel |

---

#### `components/StatusBar.tsx`

Health indicator showing GPU, models, resume count.

---

## 6. Interview Agent — `interview_agent/`

> This is the **legacy standalone voice interview engine**. Most of its functionality has been superseded by the browser-based interview in `candidate/interview/page.tsx`. The routes in `interview_routes.py` still reference some parts for the WebSocket audio path.

#### `interview_agent/interview_engine.py`

State machine for interview flow.

**States:** `NOT_STARTED → INTRO → BEHAVIORAL → DOMAIN → FOLLOWUP → SCENARIO → CLOSING → COMPLETE`

**Adaptive difficulty:** Tracks consecutive good/weak answers, adjusts next question difficulty.

**Config:** `InterviewConfig(role, experience_level, domain, language, num_questions, difficulty)`

---

#### `interview_agent/confidence_analyzer.py`

Tracks candidate confidence via speech patterns, response structure, coherence. Generates a summary dict used in the final report.

---

#### `interview_agent/cheating_detector.py`

Tracks frontend-reported signals: tab switch, copy, paste, DevTools open. Accumulates flags and produces an integrity report.

---

#### `interview_agent/scoring.py`

Combines answer quality, confidence scores, and cheating deductions → final recommendation (Hire / Maybe / No Hire).

---

#### `interview_agent/processing.py`

Audio processing pipeline:
- `transcribe_audio(bytes)` → Whisper local OR Sarvam AI STT
- `generate_interview_response_stream(context)` → Groq (fast) OR Ollama
- `InterviewBrain` → full conversational AI engine

---

#### `interview_agent/output_handler.py`

Text-to-speech:
- SarvamAI TTS (Indian English, multiple speakers)
- Coqui VITS (local fallback)
- Streams audio to LiveKit TX

---

## 7. Database Schema

```sql
-- Recruitment sessions
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    jd_text TEXT NOT NULL,
    cv_directory TEXT NOT NULL,
    status TEXT DEFAULT 'processing',    -- processing | completed
    total_resumes INTEGER DEFAULT 0,
    selected_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    cutoff_score REAL DEFAULT 0.55,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    session_questions TEXT DEFAULT '[]'  -- JSON array of QuestionItem
);

-- Candidates per session
CREATE TABLE candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    resume_id TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    filename TEXT NOT NULL,
    semantic_score REAL DEFAULT 0,       -- 0-1 (vector similarity)
    llm_score REAL DEFAULT 0,            -- 0-1 (LLM evaluation)
    final_score REAL DEFAULT 0,          -- 0.4×semantic + 0.6×llm
    matched_skills TEXT DEFAULT '[]',    -- JSON string array
    missing_skills TEXT DEFAULT '[]',    -- JSON string array
    summary TEXT DEFAULT '',
    rank INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',       -- pending | selected | rejected
    created_at TEXT NOT NULL
);

-- Resume metadata (independent of sessions)
CREATE TABLE resumes (
    resume_id TEXT PRIMARY KEY,
    candidate_name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    filename TEXT NOT NULL,
    file_path TEXT DEFAULT '',
    sections TEXT DEFAULT '[]',          -- JSON: {education, experience, ...}
    chunk_count INTEGER DEFAULT 0,
    uploaded_at TEXT NOT NULL
);

-- Email templates
CREATE TABLE email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    template_type TEXT DEFAULT 'selection',  -- selection | rejection
    created_at TEXT NOT NULL
);

-- Email send log
CREATE TABLE email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    resume_id TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    email_to TEXT NOT NULL,
    template_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    sent_at TEXT
);

-- Interview sessions (one per candidate per recruitment session)
CREATE TABLE interview_sessions (
    id TEXT PRIMARY KEY,
    recruitment_session_id TEXT NOT NULL REFERENCES sessions(id),
    candidate_id TEXT NOT NULL,
    candidate_name TEXT DEFAULT '',
    token TEXT UNIQUE NOT NULL,          -- URL token for candidate link
    question_config TEXT DEFAULT '{}',  -- JSON: {role, questions, candidate_name, email, ...}
    status TEXT DEFAULT 'pending',       -- pending | active | completed
    interview_url TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    report TEXT,                         -- JSON: enriched transcript + scores + recommendation
    audio_path TEXT DEFAULT ''           -- Path to .webm audio file on disk
);
```

---

## 8. Data Flow Diagrams

### Resume Ingestion
```
Recruiter uploads CVs (directory scan or file upload)
  ↓
routes.py: /sessions/start or /resumes/scan-directory
  ↓
For each PDF/DOCX:
  resume_parser.parse_resume(bytes, filename)
    → {resume_id, name, email, phone, sections, chunks}
  embedding_service.encode([chunk.text for chunk in chunks])
    → List[List[float]]  (384-dim vectors)
  vector_store.add_resume_chunks(chunks, embeddings)
    → stored in ChromaDB
  database.save_resume_meta(...)
    → stored in SQLite resumes table
```

### Candidate Matching
```
Recruiter provides JD text
  ↓
matching_engine.match(jd_text, top_k)
  ↓
embedding_service.encode_single(jd_text) → query_vector
  ↓
vector_store.query(query_vector, top_k×2)
  → semantic_score per resume (cosine similarity, weighted top-3 chunks)
  ↓
For each semantic candidate:
  sarvam_scorer.score_candidate(jd, chunks, name)  [if API key]
  OR llm_scorer.score_candidate(...)               [Ollama]
  OR keyword_fallback()
  → llm_score (0-1), matched_skills, missing_skills, summary
  ↓
final_score = 0.4×semantic + 0.6×llm
  ↓
Filter by cutoff, rank, save to DB → return to recruiter
```

### Interview Lifecycle
```
RECRUITER:
  Configures question bank (SessionQuestionsPanel)
    → QuestionItem[]: {question, expected_answer, key_points}
    → POST /sessions/{id}/questions

  Generates interview links (InterviewSetupModal)
    → POST /sessions/{id}/bulk-generate-interviews
    → Creates interview_sessions rows in DB (token per candidate)
    → Returns interview_url = http://localhost:3000/candidate/interview?token={token}

CANDIDATE:
  Opens interview_url in browser
    → GET /api/interview-session/{token}  → config (name, role, questions)
  Reviews profile info, adds notes
    → POST /api/interview/checkin
  Interview runs (question loop in browser):
    - SpeechSynthesis speaks questions
    - SpeechRecognition captures answers
    - POST /api/interview/ai-respond → transition phrases
    - MediaRecorder captures entire audio as WebM
  At end:
    → POST /api/interview-session/{token}/submit-report
         backend: LLM scores transcript with JD context
         → enriched report stored in DB
    → POST /api/interview-session/{token}/audio  (WebM blob)

RECRUITER:
  Views report in dashboard (InterviewReportPanel)
    → GET /sessions/{id}/candidates/{rid}/interview-report
    → Shows: overall score, recommendation, per-question feedback,
             key points hit/missed, integrity flags, audio playback
```

---

## 9. Scoring System

### Candidate Matching Score

```
final_score = (0.4 × semantic_score) + (0.6 × llm_score)

semantic_score = 1 - (chromadb_cosine_distance / 2)
                 weighted across top-3 chunks: [0.5, 0.3, 0.2]

llm_score = 0-1 from LLM evaluation
            (sarvam → ollama → keyword fallback)
```

Change weights in `matching_engine.py` line with `final = semantic * 0.4 + llm * 0.6`.

---

### Interview Answer Score (per question)

Scored by `InterviewAgent.score_transcript()` at report submission time.

```
LLM prompt includes:
  - JD text (first 2000 chars)
  - Role name
  - The specific question
  - Recruiter's expected_answer (if set)
  - key_points to check (if set)
  - Candidate's verbatim answer

Rubric:
  9-10  Excellent: directly addresses question, role-relevant, concrete, depth
  7-8   Good: solid, relevant, minor gaps
  5-6   Adequate: partially addresses, some relevance, vague
  3-4   Weak: mostly off-topic, generic, no substance
  0-2   Poor: irrelevant, nonsensical, clearly fabricated

overall_score = average(per-question scores)

Recommendation:
  ≥ 7.5  → Strong Hire
  ≥ 6.0  → Hire
  ≥ 4.5  → Maybe
  < 4.5  → No Hire
```

**Fallback (when no LLM):** Keyword overlap against key_points → expected_answer words → JD words. Never pure word count.

---

## 10. Environment Variables

Full list in `.env`:

```bash
# Server
HOST=0.0.0.0
PORT=8000
DEBUG=true

# GPU — set "cuda" to force GPU, "cpu" to force CPU
DEVICE=auto

# Embedding model (do not change unless you want to re-embed all resumes)
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Local LLM via Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral:7b-instruct-q4_K_M

# Sarvam AI (cloud LLM — set this for better quality, especially without GPU)
SARVAM_API_KEY=your_key_here
LLM_PROVIDER=auto   # auto | sarvam | ollama | fallback

# ChromaDB
CHROMA_PERSIST_DIR=./vectorstore
CHROMA_COLLECTION_NAME=resumes

# Resume processing
CHUNK_SIZE=512
CHUNK_OVERLAP=50
MAX_RESUME_SIZE_MB=10
SUPPORTED_FORMATS=.pdf,.docx

# Matching thresholds
TOP_K_CANDIDATES=10
MIN_MATCH_SCORE=0.35

# LiveKit (for WebRTC voice interview)
LIVEKIT_URL=wss://your-livekit-cloud-url
LIVEKIT_API_KEY=your_key
LIVEKIT_API_SECRET=your_secret
```

---

## 11. API Reference

All endpoints under FastAPI at `http://localhost:8000`.

Swagger UI available at: `http://localhost:8000/docs`

### Recruitment API (`/api/v1`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | System status |
| POST | `/resumes/upload` | Upload PDF/DOCX files |
| POST | `/resumes/scan-directory?directory=...` | Bulk scan local folder |
| GET | `/resumes` | List all resumes |
| DELETE | `/resumes` | Delete all resumes + vectors |
| DELETE | `/resumes/{id}` | Delete one resume |
| POST | `/match` | Match candidates to JD |
| GET | `/resume/{id}/preview` | Get resume text |
| POST | `/browse` | Filesystem navigation |
| POST | `/read-file` | Read JD from file |
| POST | `/sessions/start` | Create session + scan + match |
| GET | `/sessions` | List sessions |
| GET | `/sessions/{id}` | Session detail |
| DELETE | `/sessions/{id}` | Delete session |
| GET | `/sessions/{id}/candidates` | List candidates |
| POST | `/sessions/{id}/candidates/{rid}/status` | Change status |
| GET | `/templates` | Email templates |
| POST | `/templates` | Create template |
| POST | `/sessions/{id}/bulk-action` | Bulk email / status change |
| GET | `/sessions/{id}/emails` | Email log |
| POST | `/sessions/{id}/update-cutoff` | Re-classify by cutoff |
| GET | `/dashboard` | Aggregated stats |
| GET | `/sessions/{id}/questions` | Get question bank |
| POST | `/sessions/{id}/questions` | Save question bank (JSON body) |
| POST | `/sessions/{id}/questions/generate` | LLM generate + save |
| POST | `/sessions/{id}/generate-questions` | LLM generate (preview) |
| POST | `/sessions/{id}/candidates/{rid}/generate-interview` | Create interview link |
| POST | `/sessions/{id}/bulk-generate-interviews` | Bulk create links |
| GET | `/sessions/{id}/interviews` | All interview sessions |
| GET | `/interview/{token}` | Interview config by token |
| POST | `/interview/{token}/complete` | Mark completed |
| GET | `/sessions/{id}/candidates/{rid}/interview-report` | Recruiter report |
| POST | `/sessions/{id}/candidates/{rid}/score-answers` | On-demand LLM scoring |

### Interview API (no prefix)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/interview-session/{token}` | Candidate fetch config |
| POST | `/api/interview/checkin` | Candidate pre-interview notes |
| POST | `/api/interview/ai-respond` | AI transition phrase |
| POST | `/api/cheating/report` | Log cheating signal |
| GET | `/api/token` | LiveKit token |
| WS | `/ws/audio` | PCM audio stream |
| POST | `/api/interview-session/{token}/submit-report` | Submit + score transcript |
| POST | `/api/interview-session/{token}/audio` | Upload WebM audio |
| GET | `/api/interview-session/{token}/audio` | Download audio |
| GET | `/api/interview-session/{token}/report` | Get report |

---

## 12. Technology Choices

| Layer | Technology | Why |
|-------|-----------|-----|
| **Web Framework** | FastAPI | Async, fast, auto-docs, Pydantic validation |
| **Frontend** | Next.js 15 + React 19 | App Router, server components, modern |
| **Styles** | Tailwind CSS 4 | Utility-first, no build step for inline styles |
| **Embedding Model** | all-MiniLM-L6-v2 | 80 MB, 384 dims, fast, low VRAM |
| **Vector DB** | ChromaDB | File-based, no server, cosine similarity built-in |
| **Resume Parsing** | pdfplumber + python-docx | Lightweight, reliable table extraction |
| **Local LLM** | Ollama + mistral-7b-q4 | Quantized, fits in 4 GB VRAM |
| **Cloud LLM** | Sarvam AI (sarvam-m) | 24B multilingual, affordable, Indian-market focused |
| **Interview STT** | Web Speech API | Browser-native, no server cost, works offline |
| **Interview TTS** | SpeechSynthesis API | Browser-native, no latency |
| **Database** | SQLite + aiosqlite | Zero setup, file-based, persistent, async |
| **Audio Storage** | Local filesystem (.webm) | Simple, direct file serve via FileResponse |
| **Voice Interview** | MediaRecorder API | Captures full audio for recruiter playback |

---

## 13. How to Add a New Feature

### Add a new API endpoint (backend)

1. Decide: does it belong in `routes.py` (recruitment) or `interview_routes.py` (interview)?
2. Add the function to the appropriate file
3. If it needs DB access, add a function to `database.py`
4. If it calls an LLM, use `InterviewAgent._try_sarvam()` / `_try_ollama()` pattern
5. Add a typed wrapper in `frontend/src/lib/api.ts`
6. Call from the appropriate page component

### Add a new column to the database

1. Add the column to the `CREATE TABLE` statement in `database.py` (for new installs)
2. Add an `ALTER TABLE` migration in `init_db()` inside the try/except block (for existing installs):
   ```python
   try:
       await db.execute("ALTER TABLE your_table ADD COLUMN new_col TEXT DEFAULT ''")
       await db.commit()
   except Exception:
       pass  # Column already exists
   ```
3. Update the relevant CRUD functions to read/write the new column

### Add a new page (frontend)

1. Create `frontend/src/app/your-page/page.tsx` with `"use client"` at top
2. If it uses `useSearchParams()`, wrap the component in `<Suspense>`
3. Add navigation link in `recruiter/page.tsx` or wherever appropriate

### Change the scoring weights

- **Resume matching:** In `matching_engine.py`, find `final = semantic * 0.4 + llm * 0.6` and adjust
- **Interview scoring thresholds:** In `interview_routes.py`, find the `if avg >= 7.5` block in `submit_interview_report`
- **Interview scoring rubric:** In `interview_agent.py`, update `_build_scoring_prompt()` prompt text

### Add a new LLM provider

1. Add a new `_try_yourprovider(prompt, max_tokens)` method in `InterviewAgent`
2. Add it to the chain in `generate_questions()` and `score_transcript()` before the fallback
3. Add the API key to `.env` and read it via `os.getenv()`
