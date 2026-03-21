"""
API Routes.
Handles resume uploads, JD matching, and data management.
"""

import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from loguru import logger
from app.services import database as db
from datetime import datetime

from app.models.schemas import (
    UploadResponse,
    MatchRequest,
    MatchResult,
    HealthResponse,
)
from app.core.config import get_settings

router = APIRouter()

# These will be injected from app.py via dependency
_services = {}


def set_services(services: dict):
    """Inject service instances from app startup."""
    global _services
    _services = services


def get_embedding_service():
    return _services["embedding"]


def get_vector_store():
    return _services["vector_store"]


def get_matching_engine():
    return _services["matching_engine"]


def get_resume_store():
    """Simple in-memory store for resume metadata."""
    return _services["resume_store"]


# ── Upload Resumes ─────────────────────────────

@router.post("/resumes/upload", response_model=list[UploadResponse])
async def upload_resumes(
    files: list[UploadFile] = File(..., description="PDF or DOCX resume files"),
):
    """
    Upload one or more resumes. Each is parsed, chunked, embedded,
    and stored in the vector database.
    """
    settings = get_settings()
    embedding = get_embedding_service()
    store = get_vector_store()
    resume_store = get_resume_store()

    from app.services.resume_parser import parse_resume

    results = []

    for file in files:
        # Validate
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in settings.supported_formats_list:
            results.append(
                UploadResponse(
                    resume_id="",
                    filename=file.filename,
                    candidate_name="",
                    status=f"rejected — unsupported format: {ext}",
                )
            )
            continue

        try:
            # Read file
            content = await file.read()

            if len(content) > settings.max_resume_bytes:
                results.append(
                    UploadResponse(
                        resume_id="",
                        filename=file.filename,
                        candidate_name="",
                        status=f"rejected — file too large (max {settings.MAX_RESUME_SIZE_MB}MB)",
                    )
                )
                continue

            # Parse
            parsed = parse_resume(
                file_bytes=content,
                filename=file.filename,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
            )

            # Embed chunks
            chunk_texts = [c["text"] for c in parsed["chunks"]]
            embeddings = embedding.encode(chunk_texts)

            # Store in vector DB
            store.add_resume_chunks(parsed["chunks"], embeddings)

            # Store metadata in memory
            resume_store[parsed["resume_id"]] = {
                "resume_id": parsed["resume_id"],
                "filename": parsed["filename"],
                "candidate_name": parsed["candidate_name"],
                "email": parsed["email"],
                "phone": parsed["phone"],
                "sections": list(parsed["sections"].keys()),
                "chunk_count": len(parsed["chunks"]),
            }

            results.append(
                UploadResponse(
                    resume_id=parsed["resume_id"],
                    filename=parsed["filename"],
                    candidate_name=parsed["candidate_name"],
                    status="processed",
                    chunk_count=len(parsed["chunks"]),
                )
            )

            logger.info(f"Resume processed: {parsed['candidate_name']} ({parsed['resume_id']})")

        except Exception as e:
            logger.error(f"Failed to process {file.filename}: {e}")
            results.append(
                UploadResponse(
                    resume_id="",
                    filename=file.filename,
                    candidate_name="",
                    status=f"error — {str(e)}",
                )
            )

    return results


# ── Match JD Against Resumes ───────────────────

@router.post("/match", response_model=MatchResult)
async def match_jd(request: MatchRequest):
    """
    Match a job description against all stored resumes.
    Returns ranked candidates with scores.
    """
    engine = get_matching_engine()
    store = get_vector_store()
    resume_store = get_resume_store()

    if store.get_total_resumes() == 0:
        raise HTTPException(
            status_code=400,
            detail="No resumes in the database. Upload resumes first.",
        )

    jd_id = str(uuid.uuid4())[:12]

    result = await engine.match(
        jd_text=request.jd_text,
        jd_title=request.jd_title,
        jd_id=jd_id,
        top_k=request.top_k,
        min_score=request.min_score,
    )

    # Enrich candidates with stored metadata (email, phone)
    for candidate in result.candidates:
        meta = resume_store.get(candidate.resume_id, {})
        candidate.email = meta.get("email", "")

    return result


# ── Resume Management ──────────────────────────

@router.get("/resumes", response_model=list[dict])
async def list_resumes():
    """List all uploaded resumes."""
    resume_store = get_resume_store()
    return list(resume_store.values())


@router.delete("/resumes/{resume_id}")
async def delete_resume(resume_id: str):
    """Delete a resume from the system."""
    store = get_vector_store()
    resume_store = get_resume_store()

    if resume_id not in resume_store:
        raise HTTPException(status_code=404, detail="Resume not found")

    store.delete_resume(resume_id)
    del resume_store[resume_id]

    return {"status": "deleted", "resume_id": resume_id}


@router.delete("/resumes")
async def reset_all():
    """Delete all resumes. Use with caution."""
    store = get_vector_store()
    resume_store = get_resume_store()

    store.reset()
    resume_store.clear()

    return {"status": "reset", "message": "All resumes deleted"}


# ── Health Check ───────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health and status."""
    settings = get_settings()
    store = get_vector_store()

    import torch
    gpu_info = "none"
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        gpu_info = f"{name} ({vram:.1f}GB)"

    return HealthResponse(
        status="healthy",
        gpu=gpu_info,
        embedding_model=settings.EMBEDDING_MODEL,
        llm_model=settings.LLM_PROVIDER,
        total_resumes=store.get_total_resumes(),
    )


# ── Directory Scanning ─────────────────────────

@router.post("/resumes/scan-directory")
async def scan_directory(directory: str = ""):
    """
    Scan a local directory for resume files (PDF/DOCX).
    Parses, embeds, and stores all found resumes.
    Used by the NextJS frontend to batch-import from a folder.
    """
    from pathlib import Path
    from app.services.resume_parser import parse_resume

    settings = get_settings()
    embedding = get_embedding_service()
    store = get_vector_store()
    resume_store = get_resume_store()

    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {directory}")

    # Find all supported resume files
    files_found = []
    for ext in settings.supported_formats_list:
        files_found.extend(dir_path.glob(f"*{ext}"))
        files_found.extend(dir_path.glob(f"*{ext.upper()}"))

    if not files_found:
        raise HTTPException(
            status_code=400,
            detail=f"No resume files ({settings.SUPPORTED_FORMATS}) found in {directory}",
        )

    results = []
    for file_path in files_found:
        try:
            content = file_path.read_bytes()

            if len(content) > settings.max_resume_bytes:
                results.append({"filename": file_path.name, "status": "skipped — too large"})
                continue

            parsed = parse_resume(
                file_bytes=content,
                filename=file_path.name,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
            )

            chunk_texts = [c["text"] for c in parsed["chunks"]]
            embeddings = embedding.encode(chunk_texts)
            store.add_resume_chunks(parsed["chunks"], embeddings)

            resume_store[parsed["resume_id"]] = {
                "resume_id": parsed["resume_id"],
                "filename": parsed["filename"],
                "candidate_name": parsed["candidate_name"],
                "email": parsed["email"],
                "phone": parsed["phone"],
                "sections": list(parsed["sections"].keys()),
                "chunk_count": len(parsed["chunks"]),
            }

            results.append({
                "filename": file_path.name,
                "resume_id": parsed["resume_id"],
                "candidate_name": parsed["candidate_name"],
                "chunks": len(parsed["chunks"]),
                "status": "processed",
            })

        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}")
            results.append({"filename": file_path.name, "status": f"error — {str(e)}"})

    return {
        "directory": str(directory),
        "total_found": len(files_found),
        "processed": len([r for r in results if r["status"] == "processed"]),
        "results": results,
    }


@router.post("/resumes/list-directory")
async def list_directory_files(directory: str = ""):
    """List resume files in a directory without processing them."""
    from pathlib import Path

    settings = get_settings()
    dir_path = Path(directory)

    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {directory}")

    files = []
    for ext in settings.supported_formats_list:
        for f in dir_path.glob(f"*{ext}"):
            files.append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "path": str(f),
            })
        for f in dir_path.glob(f"*{ext.upper()}"):
            files.append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "path": str(f),
            })

    return {"directory": str(directory), "files": files, "count": len(files)}


# ── Directory Browser ──────────────────────────

@router.post("/browse")
async def browse_directory(path: str = ""):
    """
    Browse the filesystem. Returns folders and files at the given path.
    Used by the frontend to let users pick CV directories and JD files.
    """
    from pathlib import Path

    target = Path(path) if path else Path.home() / "Desktop"

    if not target.exists():
        # Try common locations
        for fallback in [Path.home() / "Desktop", Path.home() / "Documents", Path.home()]:
            if fallback.exists():
                target = fallback
                break

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    items = []
    try:
        for item in sorted(target.iterdir()):
            # Skip hidden files and system folders
            if item.name.startswith(".") or item.name.startswith("$"):
                continue
            if item.name in ("node_modules", "__pycache__", "venv", ".git"):
                continue

            try:
                if item.is_dir():
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "folder",
                        "size": None,
                    })
                else:
                    ext = item.suffix.lower()
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "file",
                        "ext": ext,
                        "size": round(item.stat().st_size / 1024, 1),
                    })
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    return {
        "current": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "items": items,
    }

@router.post("/read-file")
async def read_file(path: str = ""):
    """Read a JD file (PDF/DOCX/TXT) and return its text content."""
    from pathlib import Path
    from app.services.resume_parser import extract_text_from_pdf, extract_text_from_docx

    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")

    ext = file_path.suffix.lower()
    content = file_path.read_bytes()

    if ext == ".pdf":
        text = extract_text_from_pdf(content)
    elif ext == ".docx":
        text = extract_text_from_docx(content)
    elif ext == ".txt":
        text = content.decode("utf-8", errors="ignore")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    return {"filename": file_path.name, "text": text}


# ── Session Management ─────────────────────────

@router.post("/sessions/start")
async def start_session(
    title: str = "",
    jd_text: str = "",
    cv_directory: str = "",
    cutoff_score: float = 0.55,
):
    """
    Start a new recruitment session:
    1. Create session in DB
    2. Scan CV directory
    3. Match against JD
    4. Save results
    5. Organize files into Selected/Rejected folders
    """
    import shutil
    from pathlib import Path
    from app.services.resume_parser import parse_resume

    settings = get_settings()
    embedding = get_embedding_service()
    store = get_vector_store()
    engine = get_matching_engine()
    resume_store = get_resume_store()

    session_id = str(uuid.uuid4())[:12]

    # 1. Create session
    await db.create_session(
        session_id=session_id,
        title=title or "Untitled Position",
        jd_text=jd_text,
        cv_directory=cv_directory,
        cutoff_score=cutoff_score,
    )

    # 2. Clear previous vectors and scan directory
    store.reset()
    resume_store.clear()

    dir_path = Path(cv_directory)
    if not dir_path.exists() or not dir_path.is_dir():
        await db.update_session(session_id, status="failed")
        raise HTTPException(status_code=400, detail=f"Directory not found: {cv_directory}")

    files_found = []
    for ext in settings.supported_formats_list:
        files_found.extend(dir_path.glob(f"*{ext}"))

    # Deduplicate by filename
    seen_names = set()
    unique_files = []
    for f in files_found:
        if f.name.lower() not in seen_names:
            seen_names.add(f.name.lower())
            unique_files.append(f)
    files_found = unique_files

    processed = 0
    errors = []

    for file_path in files_found:
        try:
            content = file_path.read_bytes()
            if len(content) > settings.max_resume_bytes:
                continue

            parsed = parse_resume(
                file_bytes=content,
                filename=file_path.name,
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
            )

            chunk_texts = [c["text"] for c in parsed["chunks"]]
            embeddings = embedding.encode(chunk_texts)
            store.add_resume_chunks(parsed["chunks"], embeddings)

            resume_store[parsed["resume_id"]] = {
                "resume_id": parsed["resume_id"],
                "filename": parsed["filename"],
                "candidate_name": parsed["candidate_name"],
                "email": parsed["email"],
                "phone": parsed["phone"],
                "sections": list(parsed["sections"].keys()),
                "chunk_count": len(parsed["chunks"]),
            }

            # Save resume to DB
            await db.save_resume_meta(
                resume_id=parsed["resume_id"],
                candidate_name=parsed["candidate_name"],
                email=parsed["email"],
                phone=parsed["phone"],
                filename=parsed["filename"],
                file_path=str(file_path),
                sections=list(parsed["sections"].keys()),
                chunk_count=len(parsed["chunks"]),
            )

            processed += 1

        except Exception as e:
            errors.append({"file": file_path.name, "error": str(e)})
            logger.error(f"Failed: {file_path.name}: {e}")

    if processed == 0:
        await db.update_session(session_id, status="failed")
        raise HTTPException(status_code=400, detail="No resumes could be processed")

    # 3. Match against JD
    result = await engine.match(
        jd_text=jd_text,
        jd_title=title or "Untitled Position",
        jd_id=session_id,
        top_k=50,
        min_score=0.3,
    )

    # Enrich with email
    for candidate in result.candidates:
        meta = resume_store.get(candidate.resume_id, {})
        candidate.email = meta.get("email", "")

    # 4. Classify and save candidates
    selected_count = 0
    rejected_count = 0
    candidates_data = []

    for c in result.candidates:
        status = "selected" if c.final_score >= cutoff_score else "rejected"
        if status == "selected":
            selected_count += 1
        else:
            rejected_count += 1

        candidates_data.append({
            "resume_id": c.resume_id,
            "candidate_name": c.candidate_name,
            "email": c.email,
            "filename": c.filename,
            "semantic_score": c.semantic_score,
            "llm_score": c.llm_score,
            "final_score": c.final_score,
            "matched_skills": c.matched_skills,
            "missing_skills": c.missing_skills,
            "summary": c.summary,
            "rank": c.rank,
            "status": status,
        })

    await db.save_candidates(session_id, candidates_data)

    # 5. Organize files into Selected/Rejected directories
# Status stored in DB — no file copying needed
    # 6. Update session
    await db.update_session(
        session_id,
        status="completed",
        total_resumes=processed,
        selected_count=selected_count,
        rejected_count=rejected_count,
        completed_at=datetime.utcnow().isoformat(),
    )

    return {
        "session_id": session_id,
        "status": "completed",
        "total_resumes": processed,
        "selected": selected_count,
        "rejected": rejected_count,
        "errors": len(errors),
        "candidates": candidates_data,
    }


@router.get("/sessions")
async def list_all_sessions():
    """List all past recruitment sessions."""
    sessions = await db.list_sessions()
    return sessions


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """Get a session with all its candidates."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    candidates = await db.get_candidates(session_id)
    session["candidates"] = candidates
    return session


@router.delete("/sessions/{session_id}")
async def delete_session_route(session_id: str):
    """Delete a session and its candidates."""
    await db.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions/{session_id}/candidates")
async def get_session_candidates(session_id: str, status: str = ""):
    """Get candidates for a session, optionally filtered by status."""
    candidates = await db.get_candidates(
        session_id, status=status if status else None
    )
    return candidates


@router.post("/sessions/{session_id}/candidates/{resume_id}/status")
async def change_candidate_status(
    session_id: str, resume_id: str, status: str = ""
):
    """Manually change a candidate's status (selected/rejected)."""
    if status not in ("selected", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="Status must be: selected, rejected, or pending")
    await db.update_candidate_status(session_id, resume_id, status)
    return {"status": "updated", "resume_id": resume_id, "new_status": status}


@router.get("/resume/{resume_id}/preview")
async def preview_resume(resume_id: str):
    """Get resume text content for preview in UI."""
    from pathlib import Path
    from app.services.resume_parser import extract_text_from_pdf, extract_text_from_docx

    try:
        meta = await db.get_resume_meta(resume_id)
        if not meta:
            return {"meta": {"candidate_name": "Unknown", "filename": "N/A"}, "text": "Resume not found in database"}

        file_path = Path(meta.get("file_path", ""))
        if not file_path or not file_path.exists():
            return {"meta": meta, "text": f"File not found on disk: {meta.get('file_path', 'no path stored')}"}

        ext = file_path.suffix.lower()
        content = file_path.read_bytes()

        try:
            if ext == ".pdf":
                text = extract_text_from_pdf(content)
            elif ext == ".docx":
                text = extract_text_from_docx(content)
            else:
                text = f"Unsupported format: {ext}"
        except Exception as e:
            text = f"Could not extract text: {e}"

        return {"meta": meta, "text": text}

    except Exception as e:
        return {"meta": {"candidate_name": "Error"}, "text": f"Error: {str(e)}"}

# ── Email Templates & Bulk Actions ─────────────

@router.get("/templates")
async def list_templates(template_type: str = ""):
    """List email templates."""
    return await db.get_templates(template_type)


@router.post("/templates")
async def create_template(
    name: str = "", subject: str = "", body: str = "", template_type: str = "selection"
):
    """Create a new email template."""
    if not name or not subject or not body:
        raise HTTPException(status_code=400, detail="name, subject, and body are required")
    return await db.save_template(name, subject, body, template_type)


@router.post("/sessions/{session_id}/bulk-action")
async def bulk_action(
    session_id: str,
    action: str = "",
    resume_ids: str = "",
    template_id: int = 0,
    template_vars: str = "{}",
):
    """
    Perform bulk actions on candidates.
    action: "send_email" | "change_status" | "export"
    resume_ids: comma-separated resume IDs
    """
    import json as json_mod

    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    ids = [r.strip() for r in resume_ids.split(",") if r.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="No resume IDs provided")

    if action == "send_email":
        # Get template
        templates = await db.get_templates()
        template = None
        for t in templates:
            if t["id"] == template_id:
                template = t
                break

        if not template:
            raise HTTPException(status_code=400, detail="Template not found")

        # Get candidates
        candidates = await db.get_candidates(session_id)
        target_candidates = [c for c in candidates if c["resume_id"] in ids]

        # Parse template variables
        try:
            vars_dict = json_mod.loads(template_vars)
        except:
            vars_dict = {}

        results = []
        for c in target_candidates:
            # Fill template
            filled_subject = template["subject"]
            filled_body = template["body"]

            replacements = {
                "{{candidate_name}}": c["candidate_name"],
                "{{job_title}}": session.get("title", ""),
                "{{email}}": c.get("email", ""),
                **{f"{{{{{k}}}}}": v for k, v in vars_dict.items()},
            }

            for placeholder, value in replacements.items():
                filled_subject = filled_subject.replace(placeholder, str(value))
                filled_body = filled_body.replace(placeholder, str(value))

            # Send email via Gmail API
            email_sent = False
            to_email = c.get("email", "")
            if to_email and "@" in to_email:
                from app.services.email_service import send_bulk_email
                email_sent = send_bulk_email(
                    to_email=to_email,
                    candidate_name=c["candidate_name"],
                    subject=filled_subject,
                    body_text=filled_body,
                )

            await db.log_email(
                session_id=session_id,
                resume_id=c["resume_id"],
                candidate_name=c["candidate_name"],
                email_to=to_email or "no-email",
                template_name=template["name"],
                subject=filled_subject,
            )

            results.append({
                "candidate": c["candidate_name"],
                "email": to_email,
                "subject": filled_subject,
                "preview": filled_body[:200] + "...",
                "status": "sent" if email_sent else ("no_email" if not to_email else "failed"),
            })

        return {
            "action": "send_email",
            "total": len(results),
            "results": results,
        }

    elif action == "change_status":
        new_status = template_vars  # Reuse field for status value
        if new_status not in ("selected", "rejected", "pending"):
            raise HTTPException(status_code=400, detail="Invalid status")
        for rid in ids:
            await db.update_candidate_status(session_id, rid, new_status)
        return {"action": "change_status", "updated": len(ids), "new_status": new_status}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


@router.get("/sessions/{session_id}/emails")
async def get_session_emails(session_id: str):
    """Get email log for a session."""
    return await db.get_email_log(session_id)


@router.post("/sessions/{session_id}/update-cutoff")
async def update_cutoff(session_id: str, cutoff_score: float = 0.55):
    """
    Re-classify candidates with a new cutoff score.
    Updates status of all candidates in the session.
    """
    candidates = await db.get_candidates(session_id)
    selected = 0
    rejected = 0

    for c in candidates:
        new_status = "selected" if c["final_score"] >= cutoff_score else "rejected"
        if new_status == "selected":
            selected += 1
        else:
            rejected += 1
        await db.update_candidate_status(session_id, c["resume_id"], new_status)

    await db.update_session(
        session_id,
        cutoff_score=cutoff_score,
        selected_count=selected,
        rejected_count=rejected,
    )

    return {
        "cutoff_score": cutoff_score,
        "selected": selected,
        "rejected": rejected,
    }


# New-dashboard and session recruitemnt pannel

@router.get("/dashboard")
async def get_dashboard():
    """Dashboard overview — all profiles with stats."""
    sessions = await db.list_sessions(limit=50)
    
    total_profiles = len(sessions)
    active = [s for s in sessions if s["status"] == "completed"]
    total_candidates = sum(s.get("total_resumes", 0) for s in sessions)
    total_selected = sum(s.get("selected_count", 0) for s in sessions)
    total_rejected = sum(s.get("rejected_count", 0) for s in sessions)
    
    return {
        "total_profiles": total_profiles,
        "total_candidates": total_candidates,
        "total_selected": total_selected,
        "total_rejected": total_rejected,
        "profiles": sessions,
    }


# ════════════════════════════════════════════════
# Interview Agent Routes
# ════════════════════════════════════════════════

import json as _json

from app.agents.interview_agent import InterviewAgent as _InterviewAgent

INTERVIEW_AGENT_BASE = (
    get_settings().INTERVIEW_BASE_URL or "http://localhost:3000/candidate/interview"
)

# Module-level singleton
_interview_agent = _InterviewAgent()


@router.get("/sessions/{session_id}/questions")
async def get_session_questions_endpoint(session_id: str):
    """Return the saved question bank for this session."""
    questions = await db.get_session_questions(session_id)
    return {"questions": questions, "count": len(questions)}


@router.post("/sessions/{session_id}/questions")
async def save_session_questions_endpoint(session_id: str, request: Request):
    """Save / replace the question bank for this session."""
    try:
        body = await request.json()
        # Accept {questions: [...]} object or a raw array
        if isinstance(body, list):
            q_list = body
        else:
            q_list = body.get("questions", [])
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be a JSON array or {questions: [...]}")
    await db.save_session_questions(session_id, q_list)
    return {"saved": len(q_list), "questions": q_list}


@router.post("/sessions/{session_id}/questions/generate")
async def generate_and_save_questions(
    session_id: str,
    role: str = "",
    num_questions: int = 8,
):
    """Generate questions from JD using LLM, then persist them to the session.
    Call this ONCE per session — then interview links reuse them automatically."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    role_name = role or session.get("title", "Software Engineer")
    provider = await db.get_setting("llm_provider", "auto")
    questions = await _interview_agent.generate_questions(session["jd_text"], role_name, num_questions, provider=provider)
    await db.save_session_questions(session_id, questions)
    logger.info(f"Session {session_id}: saved {len(questions)} questions to bank (provider={provider})")
    return {"questions": questions, "role": role_name, "count": len(questions), "saved": True}


@router.post("/sessions/{session_id}/generate-questions")
async def generate_interview_questions(
    session_id: str,
    role: str = "",
    num_questions: int = 8,
):
    """Generate interview questions from the session's JD using LLM (preview only, not saved)."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    role_name = role or session.get("title", "Software Engineer")
    provider = await db.get_setting("llm_provider", "auto")
    questions = await _interview_agent.generate_questions(session["jd_text"], role_name, num_questions, provider=provider)
    return {"questions": questions, "role": role_name, "count": len(questions)}


@router.post("/sessions/{session_id}/candidates/{resume_id}/generate-interview")
async def generate_single_interview(
    session_id: str,
    resume_id: str,
    question_source: str = "jd_generated",
    custom_questions: str = "",
    role: str = "",
    difficulty: str = "adaptive",
):
    """Generate an interview link for a single candidate."""
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    candidates_all = await db.get_candidates(session_id)
    candidate = next((c for c in candidates_all if c["resume_id"] == resume_id), None)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found in this session")

    # Return existing link if already generated
    existing = await db.get_interview_session_by_candidate(session_id, resume_id)
    if existing:
        return {
            "interview_id": existing["id"],
            "token": existing["token"],
            "interview_url": existing["interview_url"],
            "status": existing["status"],
            "candidate_name": existing["candidate_name"],
            "questions_count": len(existing["question_config"].get("questions", [])),
            "already_existed": True,
        }

    role_name = role or session.get("title", "Software Engineer")
    provider = await db.get_setting("llm_provider", "auto")

    # Priority: custom > session bank > JD-generated
    if question_source == "custom" and custom_questions:
        try:
            questions = _json.loads(custom_questions)
        except Exception:
            questions = await _interview_agent.generate_questions(session["jd_text"], role_name, provider=provider)
    else:
        session_qs = await db.get_session_questions(session_id)
        if session_qs:
            questions = session_qs
            question_source = "session"
            logger.info(f"Using {len(questions)} pre-saved session questions for {candidate['candidate_name']}")
        else:
            questions = await _interview_agent.generate_questions(session["jd_text"], role_name, provider=provider)

    question_config = {
        "source": question_source,
        "role": role_name,
        "questions": questions,
        "difficulty": difficulty,
        "candidate_name": candidate["candidate_name"],
        "email": candidate.get("email", ""),
        "phone": candidate.get("phone", ""),
        "num_questions": len(questions),
    }

    interview_id = str(uuid.uuid4())
    token = str(uuid.uuid4()).replace("-", "")
    interview_url = f"{INTERVIEW_AGENT_BASE}?token={token}"

    await db.create_interview_session(
        interview_id=interview_id,
        recruitment_session_id=session_id,
        candidate_id=resume_id,
        candidate_name=candidate["candidate_name"],
        token=token,
        question_config=question_config,
        interview_url=interview_url,
    )

    logger.info(f"Interview link generated for {candidate['candidate_name']} | token={token[:8]}…")

    # Auto-send email to candidate
    candidate_email = candidate.get("email", "")
    email_sent = False
    if candidate_email:
        from app.services.email_service import send_interview_invite
        email_sent = send_interview_invite(
            to_email=candidate_email,
            candidate_name=candidate["candidate_name"],
            job_title=role_name,
            interview_url=interview_url,
        )
        if not email_sent:
            logger.warning(f"Email not sent to {candidate_email} — check Gmail credentials in .env")

    return {
        "interview_id": interview_id,
        "token": token,
        "interview_url": interview_url,
        "status": "pending",
        "candidate_name": candidate["candidate_name"],
        "candidate_email": candidate_email,
        "email_sent": email_sent,
        "questions_count": len(questions),
        "already_existed": False,
    }


@router.post("/sessions/{session_id}/bulk-generate-interviews")
async def bulk_generate_interviews(
    session_id: str,
    resume_ids: str,
    question_source: str = "jd_generated",
    custom_questions: str = "",
    role: str = "",
    difficulty: str = "adaptive",
):
    """Generate interview links for multiple candidates at once."""
    ids = [r.strip() for r in resume_ids.split(",") if r.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="No resume IDs provided")

    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    role_name = role or session.get("title", "Software Engineer")
    provider = await db.get_setting("llm_provider", "auto")

    # Generate questions once — same for all candidates in this session
    # Priority: custom > session bank > JD-generated
    if question_source == "custom" and custom_questions:
        try:
            questions = _json.loads(custom_questions)
        except Exception:
            questions = await _interview_agent.generate_questions(session["jd_text"], role_name, provider=provider)
    else:
        session_qs = await db.get_session_questions(session_id)
        if session_qs:
            questions = session_qs
            question_source = "session"
            logger.info(f"Bulk: using {len(questions)} pre-saved session questions")
        else:
            questions = await _interview_agent.generate_questions(session["jd_text"], role_name, provider=provider)

    candidates_all = await db.get_candidates(session_id)
    results = []

    for resume_id in ids:
        candidate = next((c for c in candidates_all if c["resume_id"] == resume_id), None)
        if not candidate:
            continue

        existing = await db.get_interview_session_by_candidate(session_id, resume_id)
        if existing:
            results.append({
                "resume_id": resume_id,
                "candidate_name": existing["candidate_name"],
                "interview_url": existing["interview_url"],
                "token": existing["token"],
                "status": existing["status"],
                "already_existed": True,
            })
            continue

        question_config = {
            "source": question_source,
            "role": role_name,
            "questions": questions,
            "difficulty": difficulty,
            "candidate_name": candidate["candidate_name"],
            "email": candidate.get("email", ""),
            "phone": candidate.get("phone", ""),
            "num_questions": len(questions),
        }

        interview_id = str(uuid.uuid4())
        token = str(uuid.uuid4()).replace("-", "")
        interview_url = f"{INTERVIEW_AGENT_BASE}?token={token}"

        await db.create_interview_session(
            interview_id=interview_id,
            recruitment_session_id=session_id,
            candidate_id=resume_id,
            candidate_name=candidate["candidate_name"],
            token=token,
            question_config=question_config,
            interview_url=interview_url,
        )

        # Auto-send email to candidate
        candidate_email = candidate.get("email", "")
        email_sent = False
        if candidate_email:
            from app.services.email_service import send_interview_invite
            email_sent = send_interview_invite(
                to_email=candidate_email,
                candidate_name=candidate["candidate_name"],
                job_title=role_name,
                interview_url=interview_url,
            )

        results.append({
            "resume_id": resume_id,
            "candidate_name": candidate["candidate_name"],
            "interview_url": interview_url,
            "token": token,
            "status": "pending",
            "candidate_email": candidate_email,
            "email_sent": email_sent,
            "already_existed": False,
        })

    logger.info(f"Bulk interview: generated {len(results)} links for session {session_id}")
    return {"results": results, "total": len(results), "questions_count": len(questions)}


@router.get("/sessions/{session_id}/interviews")
async def get_session_interviews(session_id: str):
    """Get all interview sessions for a recruitment session."""
    interviews = await db.get_interview_sessions_for_recruitment(session_id)
    stats = await db.get_interview_stats_for_recruitment(session_id)
    return {"interviews": interviews, "stats": stats, "total": len(interviews)}


@router.get("/interview/{token}")
async def get_interview_by_token(token: str):
    """Get interview config by token — called by interview agent frontend."""
    interview = await db.get_interview_session_by_token(token)
    if not interview:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")
    # Mark as active if still pending
    if interview["status"] == "pending":
        await db.update_interview_session(token, status="active")
    return interview


@router.post("/interview/{token}/complete")
async def complete_interview(token: str, report: str = ""):
    """Mark interview as completed — called by interview agent."""
    interview = await db.get_interview_session_by_token(token)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    await db.update_interview_session(
        token,
        status="completed",
        completed_at=datetime.utcnow().isoformat(),
        report=report,
    )
    return {"status": "completed", "token": token}


@router.get("/sessions/{session_id}/candidates/{resume_id}/interview-report")
async def get_candidate_interview_report(session_id: str, resume_id: str):
    """Return stored interview report for a candidate in a session (recruiter view)."""
    interview = await db.get_interview_session_by_candidate(session_id, resume_id)
    if not interview:
        raise HTTPException(status_code=404, detail="No interview found for this candidate")
    import json as _json2
    report_raw = interview.get("report") or "{}"
    try:
        report = _json2.loads(report_raw)
    except Exception:
        report = {}
    from pathlib import Path as _Path
    audio_path = interview.get("audio_path", "")
    video_path = interview.get("video_path", "")
    has_audio = bool(audio_path and _Path(audio_path).exists())
    has_video = bool(video_path and _Path(video_path).exists())
    token = interview.get("token", "")
    return {
        "token": token,
        "candidate_name": interview.get("candidate_name", ""),
        "status": interview.get("status", "pending"),
        "report": report,
        "has_audio": has_audio,
        "audio_url": f"/api/interview-session/{token}/audio" if has_audio else None,
        "has_video": has_video,
        "video_url": f"/api/interview-session/{token}/video" if has_video else None,
        "completed_at": interview.get("completed_at"),
        "interview_url": interview.get("interview_url", ""),
    }


@router.post("/sessions/{session_id}/candidates/{resume_id}/score-answers")
async def score_candidate_answers(session_id: str, resume_id: str, request: Request):
    """
    On-demand scoring: score a transcript against session questions using LLM.
    Body: { "transcript": [{question, answer}, ...] }
    Returns: { "scores": [{score, feedback, key_points_hit, key_points_missed}] }
    """
    body = await request.json()
    transcript = body.get("transcript", [])
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript is required")

    provider = await db.get_setting("llm_provider", "auto")
    questions_config = await db.get_session_questions(session_id)
    scores = await _interview_agent.score_transcript(transcript, questions_config, provider=provider)
    return {"scores": scores, "count": len(scores)}


# ── App Settings ──────────────────────────────────────────────────────────────

VALID_PROVIDERS = {"auto", "sarvam", "ollama"}


@router.get("/settings")
async def get_app_settings():
    """Return current application settings."""
    return {
        "llm_provider": await db.get_setting("llm_provider", "auto"),
    }


@router.patch("/settings")
async def update_app_settings(request: Request):
    """Update application settings. Body: { llm_provider: 'auto'|'sarvam'|'ollama' }"""
    body = await request.json()
    if "llm_provider" in body:
        provider = body["llm_provider"]
        if provider not in VALID_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Invalid provider. Use: {', '.join(VALID_PROVIDERS)}")
        await db.set_setting("llm_provider", provider)
    return {
        "ok": True,
        "llm_provider": await db.get_setting("llm_provider", "auto"),
    }