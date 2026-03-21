"""
╔══════════════════════════════════════════════════════════╗
║   AI Recruitment Agent — Resume Parser + RAG Pipeline   ║
║   Optimized for GTX 1650 Ti (4GB) / RTX 3050 (6GB)     ║
╚══════════════════════════════════════════════════════════╝

Entry point. Initializes all services and starts the FastAPI server.

Usage:
    python app.py
    # or
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

GPU Memory Budget:
    ┌──────────────────────┬──────────┬──────────┐
    │ Component            │ 1650 Ti  │ 3050     │
    ├──────────────────────┼──────────┼──────────┤
    │ Embedding model      │ ~400MB   │ ~1.2GB   │
    │ Ollama LLM           │ ~2.5GB   │ ~4GB     │
    │ ChromaDB (CPU/RAM)   │ 0        │ 0        │
    │ ─────────────────    │ ──────── │ ──────── │
    │ Total                │ ~2.9GB   │ ~5.2GB   │
    │ Available            │  4GB     │  6GB     │
    │ Headroom             │ ~1.1GB   │ ~0.8GB   │
    └──────────────────────┴──────────┴──────────┘
"""

import sys
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from app.services.database import init_db, create_default_templates, load_all_resume_meta

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import get_settings
from app.core.gpu import get_device, log_gpu_usage
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.services.llm_scorer import LLMScorer
from app.services.sarvam_scorer import SarvamScorer
from app.services.matching_engine import MatchingEngine
from app.api.routes import router, set_services
from app.api.interview_routes import router as interview_router, set_interview_agent


# ── Configure Logging ──────────────────────────

logger.remove()
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <7}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
        "<level>{message}</level>"
    ),
    level="DEBUG",
)
logger.add("logs/agent.log", rotation="10 MB", retention="7 days", level="INFO")


# ── Service Instances (module-level) ───────────

embedding_service: EmbeddingService | None = None
vector_store: VectorStoreService | None = None
llm_scorer: LLMScorer | None = None
matching_engine: MatchingEngine | None = None
resume_store: dict = {}  # In-memory metadata store (will move to DB later)


# ── App Lifecycle ──────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global embedding_service, vector_store, llm_scorer, matching_engine, resume_store

    settings = get_settings()

    logger.info("=" * 60)
    logger.info("  AI Recruitment Agent — Starting Up")
    logger.info("=" * 60)

    # 0. Initialize database and restore resume metadata
    await init_db()
    await create_default_templates()
    resume_store.update(await load_all_resume_meta())
    logger.info(f"  Restored {len(resume_store)} resumes from database")
    # 1. Detect GPU
    device = get_device(settings.DEVICE)

    # 2. Initialize embedding model
    embedding_service = EmbeddingService(
        model_name=settings.EMBEDDING_MODEL,
        device=device,
    )
    embedding_service.load()

    # 3. Initialize vector store
    vector_store = VectorStoreService(
        persist_dir=settings.CHROMA_PERSIST_DIR,
        collection_name=settings.CHROMA_COLLECTION_NAME,
    )
    vector_store.initialize()

    # 4. Initialize LLM scorer (auto: try Sarvam first, then Ollama, then fallback)
    scorer = None
    scorer_name = "fallback"

    if settings.LLM_PROVIDER in ("sarvam", "auto"):
        sarvam = SarvamScorer(api_key=settings.SARVAM_API_KEY)
        if await sarvam.check_health():
            scorer = sarvam
            scorer_name = "sarvam-m"

    if scorer is None and settings.LLM_PROVIDER in ("ollama", "auto"):
        ollama = LLMScorer(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
        )
        if await ollama.check_health():
            scorer = ollama
            scorer_name = settings.OLLAMA_MODEL

    if scorer is None:
        # Use Sarvam with fallback mode (keyword matching)
        scorer = SarvamScorer(api_key="")
        scorer_name = "keyword-fallback"
        logger.warning("No LLM available — using keyword-based fallback scoring")

    # 5. Initialize matching engine
    matching_engine = MatchingEngine(
        embedding_service=embedding_service,
        vector_store=vector_store,
        llm_scorer=scorer,
    )

    # 6. Inject services into routes
    set_services({
        "embedding": embedding_service,
        "vector_store": vector_store,
        "llm_scorer": scorer,
        "matching_engine": matching_engine,
        "resume_store": resume_store,
    })

    # 7. Try to start the interview agent as a background task
    interview_task = None
    try:
        sys.path.insert(0, str(Path(__file__).parent / "interview_agent"))
        from interview_agent.app import AIInterviewerAgent
        _agent = AIInterviewerAgent()
        set_interview_agent(_agent)
        interview_task = asyncio.create_task(_agent.run())
        logger.info("  Interview Agent started as background task")
    except Exception as e:
        logger.warning(f"  Interview agent not started (missing deps?): {e}")
        logger.info("  Interview page still served at http://localhost:8000/interview/")

    log_gpu_usage("startup complete")

    logger.info("=" * 60)
    logger.info(f"  Server ready on http://{settings.HOST}:{settings.PORT}")
    logger.info(f"  Docs:  http://{settings.HOST}:{settings.PORT}/docs")
    logger.info(f"  GPU:   {device}")
    logger.info(f"  Model: {settings.EMBEDDING_MODEL}")
    logger.info(f"  LLM:   {scorer_name}")
    logger.info("=" * 60)

    yield  # ← App runs here

    # Shutdown
    logger.info("Shutting down...")
    if interview_task and not interview_task.done():
        interview_task.cancel()
    if embedding_service:
        embedding_service.unload()
    logger.info("Shutdown complete.")


# ── Create FastAPI App ─────────────────────────

app = FastAPI(
    title="AI Recruitment Agent",
    description="Resume Parser + RAG Pipeline for automated candidate screening",
    version="0.1.0-mvp",
    lifespan=lifespan,
)

# CORS — allow the React dashboard to connect
_cors_origins_raw = get_settings().CORS_ORIGINS.strip()
_cors_origins = (
    ["*"] if _cors_origins_raw == "*"
    else [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins_raw != "*",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Mount routes
app.include_router(router, prefix="/api/v1", tags=["recruitment"])

# Interview agent routes — same paths the HTML calls (/api/interview/*, /api/cheating/*, /api/token, /ws/audio)
app.include_router(interview_router, tags=["interview"])

# Serve the interview candidate page at /interview/
_interview_static = Path(__file__).parent / "interview_agent" / "static"
if _interview_static.exists():
    app.mount("/interview", StaticFiles(directory=str(_interview_static), html=True), name="interview")


# ── Root ───────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "AI Recruitment Agent",
        "version": "0.1.0-mvp",
        "docs": "/docs",
        "interview": "/interview/",
    }


# ── Entry Point ────────────────────────────────

if __name__ == "__main__":
    settings = get_settings()

    # Create log directory
    Path("logs").mkdir(exist_ok=True)

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
