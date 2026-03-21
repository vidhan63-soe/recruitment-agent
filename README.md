# AI Recruitment Agent — Phase 1: Resume Parser + RAG Pipeline

Automated candidate screening system that parses resumes, builds a vector database, and ranks candidates against job descriptions using semantic search + LLM evaluation.

**Optimized for low-VRAM GPUs** (GTX 1650 Ti 4GB / RTX 3050 6GB).

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  PDF/DOCX   │────▶│ Resume Parser │────▶│  Chunker    │
│  Upload     │     │ (pdfplumber)  │     │ (512 chars) │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                │
                    ┌──────────────┐             │
                    │  Embedding   │◀────────────┘
                    │  (MiniLM)    │
                    │  ~400MB VRAM │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  ChromaDB    │
                    │  (local)     │
                    └──────┬───────┘
                           │
┌─────────────┐     ┌──────▼───────┐     ┌─────────────┐
│  Job Desc   │────▶│  RAG Query   │────▶│  Ollama LLM │
│  Input      │     │  (cosine)    │     │  (scoring)  │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                │
                                         ┌──────▼──────┐
                                         │  Ranked     │
                                         │  Candidates │
                                         └─────────────┘
```

## Quick Start (Windows)

```bash
# 1. Clone and run setup
setup.bat

# 2. Install Ollama (https://ollama.com/download)
ollama pull mistral:7b-instruct-q4_K_M

# 3. Start the server
python app.py

# 4. Open API docs
# http://localhost:8000/docs
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/resumes/upload` | Upload resume files (PDF/DOCX) |
| POST | `/api/v1/match` | Match JD against all resumes |
| GET | `/api/v1/resumes` | List all uploaded resumes |
| DELETE | `/api/v1/resumes/{id}` | Delete a specific resume |
| DELETE | `/api/v1/resumes` | Reset all data |
| GET | `/api/v1/health` | System health check |

## GPU Configuration

| GPU | VRAM | Embedding Model | Ollama Model | Total VRAM |
|-----|------|-----------------|--------------|------------|
| GTX 1650 Ti | 4GB | all-MiniLM-L6-v2 | phi3:mini | ~2.9GB |
| RTX 3050 | 6GB | all-MiniLM-L6-v2 | mistral:7b-q4 | ~5.2GB |
| CPU only | — | all-MiniLM-L6-v2 | phi3:mini | RAM only |

## Project Structure

```
recruitment-agent/
├── app.py                          # Main entry point
├── app/
│   ├── core/
│   │   ├── config.py               # Settings from .env
│   │   └── gpu.py                  # GPU detection & VRAM tracking
│   ├── models/
│   │   └── schemas.py              # Pydantic data models
│   ├── services/
│   │   ├── resume_parser.py        # PDF/DOCX text extraction
│   │   ├── embedding_service.py    # Sentence-transformers wrapper
│   │   ├── vector_store.py         # ChromaDB operations
│   │   ├── llm_scorer.py           # Ollama LLM candidate scoring
│   │   └── matching_engine.py      # RAG orchestration
│   └── api/
│       └── routes.py               # FastAPI endpoints
├── data/
│   ├── resumes/                    # Raw resume files
│   └── jd/                         # Job descriptions
├── vectorstore/                    # ChromaDB persistence
├── requirements.txt
├── .env.example
└── setup.bat
```

## Scoring System

Each candidate gets a **final score (0-1)** from two components:

- **Semantic Score (40%)** — Cosine similarity between JD embedding and resume chunk embeddings via ChromaDB. Top-3 chunks are weighted (0.5, 0.3, 0.2).
- **LLM Score (60%)** — Ollama evaluates skill match, experience alignment, and overall fit. Falls back to keyword matching if Ollama is unavailable.

## Next Phases

- **Phase 2**: Email notification system (SMTP + templates)
- **Phase 3**: Voice AI interview (WebRTC + Whisper + LLM)
- **Phase 4**: Recruiter dashboard (React) + licensing system
