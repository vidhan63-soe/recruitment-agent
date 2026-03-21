"""
Database Service — SQLite for recruitment session management.
Stores: sessions, candidates, scores, and history.
Zero setup, file-based, persists across restarts.
"""

import aiosqlite
import json
from datetime import datetime
from pathlib import Path
from loguru import logger


DB_PATH = "recruitment.db"


async def init_db():
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                cv_directory TEXT NOT NULL,
                status TEXT DEFAULT 'processing',
                total_resumes INTEGER DEFAULT 0,
                selected_count INTEGER DEFAULT 0,
                rejected_count INTEGER DEFAULT 0,
                cutoff_score REAL DEFAULT 0.55,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                resume_id TEXT NOT NULL,
                candidate_name TEXT NOT NULL,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                filename TEXT NOT NULL,
                semantic_score REAL DEFAULT 0,
                llm_score REAL DEFAULT 0,
                final_score REAL DEFAULT 0,
                matched_skills TEXT DEFAULT '[]',
                missing_skills TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                rank INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS resumes (
                resume_id TEXT PRIMARY KEY,
                candidate_name TEXT NOT NULL,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                filename TEXT NOT NULL,
                file_path TEXT DEFAULT '',
                sections TEXT DEFAULT '[]',
                chunk_count INTEGER DEFAULT 0,
                uploaded_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_session 
                ON candidates(session_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_status 
                ON candidates(session_id, status);


            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                template_type TEXT DEFAULT 'selection',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                resume_id TEXT NOT NULL,
                candidate_name TEXT NOT NULL,
                email_to TEXT NOT NULL,
                template_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                sent_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS interview_sessions (
                id TEXT PRIMARY KEY,
                recruitment_session_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_name TEXT DEFAULT '',
                token TEXT UNIQUE NOT NULL,
                question_config TEXT DEFAULT '{}',
                status TEXT DEFAULT 'pending',
                interview_url TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                report TEXT,
                FOREIGN KEY (recruitment_session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_interview_sessions_recruitment
                ON interview_sessions(recruitment_session_id);
            CREATE INDEX IF NOT EXISTS idx_interview_sessions_token
                ON interview_sessions(token);
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await db.commit()
        # Add session_questions column if it doesn't exist yet (migration-safe)
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN session_questions TEXT DEFAULT '[]'")
            await db.commit()
        except Exception:
            pass  # Column already exists
        # Add report + audio_path + video_path columns to interview_sessions
        for col_sql in [
            "ALTER TABLE interview_sessions ADD COLUMN report TEXT DEFAULT '{}'",
            "ALTER TABLE interview_sessions ADD COLUMN audio_path TEXT DEFAULT ''",
            "ALTER TABLE interview_sessions ADD COLUMN video_path TEXT DEFAULT ''",
        ]:
            try:
                await db.execute(col_sql)
                await db.commit()
            except Exception:
                pass  # Column already exists
    logger.info(f"Database initialized: {DB_PATH}")


# ── Session Operations ─────────────────────────

async def create_session(
    session_id: str,
    title: str,
    jd_text: str,
    cv_directory: str,
    cutoff_score: float = 0.55,
) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO sessions 
               (id, title, jd_text, cv_directory, cutoff_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, title, jd_text, cv_directory, cutoff_score, now),
        )
        await db.commit()
    return {"id": session_id, "title": title, "created_at": now}


async def update_session(session_id: str, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(session_id)
        await db.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", vals
        )
        await db.commit()


async def get_session(session_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_sessions(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def delete_session(session_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM candidates WHERE session_id = ?", (session_id,)
        )
        await db.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,)
        )
        await db.commit()


# ── Candidate Operations ───────────────────────

async def save_candidates(session_id: str, candidates: list[dict]):
    """Save match results for a session."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        for c in candidates:
            await db.execute(
                """INSERT INTO candidates 
                   (session_id, resume_id, candidate_name, email, filename,
                    semantic_score, llm_score, final_score,
                    matched_skills, missing_skills, summary, rank, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    c.get("resume_id", ""),
                    c.get("candidate_name", "Unknown"),
                    c.get("email", ""),
                    c.get("filename", ""),
                    c.get("semantic_score", 0),
                    c.get("llm_score", 0),
                    c.get("final_score", 0),
                    json.dumps(c.get("matched_skills", [])),
                    json.dumps(c.get("missing_skills", [])),
                    c.get("summary", ""),
                    c.get("rank", 0),
                    c.get("status", "pending"),
                    now,
                ),
            )
        await db.commit()


async def get_candidates(
    session_id: str, status: str | None = None
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                "SELECT * FROM candidates WHERE session_id = ? AND status = ? ORDER BY rank",
                (session_id, status),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM candidates WHERE session_id = ? ORDER BY rank",
                (session_id,),
            )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["matched_skills"] = json.loads(d.get("matched_skills", "[]"))
            d["missing_skills"] = json.loads(d.get("missing_skills", "[]"))
            results.append(d)
        return results


async def update_candidate_status(
    session_id: str, resume_id: str, status: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE candidates SET status = ? WHERE session_id = ? AND resume_id = ?",
            (status, session_id, resume_id),
        )
        await db.commit()


# ── Resume Registry ────────────────────────────

async def save_resume_meta(
    resume_id: str,
    candidate_name: str,
    email: str,
    phone: str,
    filename: str,
    file_path: str,
    sections: list[str],
    chunk_count: int,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO resumes
               (resume_id, candidate_name, email, phone, filename, 
                file_path, sections, chunk_count, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                resume_id, candidate_name, email, phone, filename,
                file_path, json.dumps(sections), chunk_count,
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()


async def load_all_resume_meta() -> dict:
    """Return all resumes as a dict keyed by resume_id (for in-memory store restore)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM resumes")
        rows = await cursor.fetchall()
        store = {}
        for row in rows:
            d = dict(row)
            d["sections"] = json.loads(d.get("sections", "[]"))
            store[d["resume_id"]] = d
        return store


async def get_resume_meta(resume_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM resumes WHERE resume_id = ?", (resume_id,)
        )
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            d["sections"] = json.loads(d.get("sections", "[]"))
            return d
        return None

# ── Email Templates ────────────────────────────

async def create_default_templates():
    """Create default email templates if none exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        count = await db.execute("SELECT COUNT(*) FROM email_templates")
        row = await count.fetchone()
        if row[0] > 0:
            return

        now = datetime.utcnow().isoformat()
        templates = [
            (
                "Selection - Interview Invite",
                "Congratulations! You've been shortlisted for {{job_title}}",
                """Dear {{candidate_name}},

Greetings from {{company_name}}!

We are pleased to inform you that after reviewing your profile, you have been shortlisted for the position of {{job_title}}.

We would like to invite you for the next round of our selection process. Please find the details below:

Position: {{job_title}}
Interview Mode: {{interview_mode}}
Date & Time: {{interview_date}}

Please confirm your availability by replying to this email.

We look forward to speaking with you!

Best regards,
{{recruiter_name}}
{{company_name}}
HR Department""",
                "selection",
                now,
            ),
            (
                "Rejection - Thank You",
                "Update on your application for {{job_title}}",
                """Dear {{candidate_name}},

Thank you for your interest in the {{job_title}} position at {{company_name}} and for taking the time to share your profile with us.

After careful consideration, we have decided to move forward with other candidates whose experience more closely aligns with our current requirements.

We truly appreciate the time you invested in exploring this opportunity. We encourage you to keep an eye on our openings, as we would be happy to consider your profile for future roles.

Wishing you all the best in your career journey.

Warm regards,
{{recruiter_name}}
{{company_name}}
HR Department""",
                "rejection",
                now,
            ),
            (
                "Selection - Assessment Link",
                "Next Steps: Online Assessment for {{job_title}}",
                """Dear {{candidate_name}},

Congratulations on being shortlisted for {{job_title}} at {{company_name}}!

As the next step, we request you to complete an online assessment. Please use the link below:

Assessment Link: {{assessment_link}}
Deadline: {{deadline}}
Duration: {{duration}}

Important Instructions:
- Ensure a stable internet connection
- Complete the assessment in one sitting
- Use a laptop/desktop for best experience

If you face any issues, please reach out to us.

Best regards,
{{recruiter_name}}
{{company_name}}""",
                "selection",
                now,
            ),
        ]

        for t in templates:
            await db.execute(
                "INSERT INTO email_templates (name, subject, body, template_type, created_at) VALUES (?, ?, ?, ?, ?)",
                t,
            )
        await db.commit()
        logger.info("Default email templates created")


async def get_templates(template_type: str = "") -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if template_type:
            cursor = await db.execute(
                "SELECT * FROM email_templates WHERE template_type = ?",
                (template_type,),
            )
        else:
            cursor = await db.execute("SELECT * FROM email_templates")
        return [dict(r) for r in await cursor.fetchall()]


async def save_template(name: str, subject: str, body: str, template_type: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cursor = await db.execute(
            "INSERT INTO email_templates (name, subject, body, template_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, subject, body, template_type, now),
        )
        await db.commit()
        return {"id": cursor.lastrowid, "name": name}


async def log_email(
    session_id: str, resume_id: str, candidate_name: str,
    email_to: str, template_name: str, subject: str,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO email_log 
               (session_id, resume_id, candidate_name, email_to, template_name, subject, status, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, 'sent', ?)""",
            (session_id, resume_id, candidate_name, email_to, template_name, subject,
             datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_email_log(session_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM email_log WHERE session_id = ? ORDER BY sent_at DESC",
            (session_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


# ── Interview Sessions ──────────────────────────

async def create_interview_session(
    interview_id: str,
    recruitment_session_id: str,
    candidate_id: str,
    candidate_name: str,
    token: str,
    question_config: dict,
    interview_url: str,
) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            """INSERT INTO interview_sessions
               (id, recruitment_session_id, candidate_id, candidate_name,
                token, question_config, status, interview_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (interview_id, recruitment_session_id, candidate_id, candidate_name,
             token, json.dumps(question_config), interview_url, now),
        )
        await db.commit()
    return {"id": interview_id, "token": token, "interview_url": interview_url}


async def get_interview_session_by_token(token: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM interview_sessions WHERE token = ?", (token,)
        )
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            d["question_config"] = json.loads(d.get("question_config", "{}"))
            return d
        return None


async def get_interview_sessions_for_recruitment(recruitment_session_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM interview_sessions WHERE recruitment_session_id = ? ORDER BY created_at DESC",
            (recruitment_session_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["question_config"] = json.loads(d.get("question_config", "{}"))
            result.append(d)
        return result


async def get_interview_session_by_candidate(
    recruitment_session_id: str, candidate_id: str
) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM interview_sessions
               WHERE recruitment_session_id = ? AND candidate_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (recruitment_session_id, candidate_id),
        )
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            d["question_config"] = json.loads(d.get("question_config", "{}"))
            return d
        return None


async def update_interview_session(token: str, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(token)
        await db.execute(
            f"UPDATE interview_sessions SET {', '.join(sets)} WHERE token = ?", vals
        )
        await db.commit()


def _normalize_question(q) -> dict:
    """Ensure a question is a QuestionItem dict (backward-compat with plain strings)."""
    if isinstance(q, str):
        return {"question": q, "expected_answer": "", "key_points": []}
    if isinstance(q, dict) and "question" in q:
        return {
            "question": q.get("question", ""),
            "expected_answer": q.get("expected_answer", ""),
            "key_points": q.get("key_points") or [],
        }
    return {"question": str(q), "expected_answer": "", "key_points": []}


async def get_session_questions(session_id: str) -> list:
    """Return the pre-generated question bank for a session as QuestionItem list."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT session_questions FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            raw = json.loads(row[0])
            return [_normalize_question(q) for q in raw]
        return []


async def save_session_questions(session_id: str, questions: list):
    """Save / replace the question bank for a session."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sessions SET session_questions = ? WHERE id = ?",
            (json.dumps(questions), session_id),
        )
        await db.commit()


# ── App Settings ─────────────────────────────────────────────────

async def get_setting(key: str, default: str = "") -> str:
    """Retrieve a single key-value setting."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    """Insert or replace a key-value setting."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()


async def get_all_settings() -> dict:
    """Return all settings as a dict."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}


async def get_interview_stats_for_recruitment(recruitment_session_id: str) -> dict:
    """Get interview stats: how many pending/completed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """SELECT status, COUNT(*) as count FROM interview_sessions
               WHERE recruitment_session_id = ? GROUP BY status""",
            (recruitment_session_id,),
        )
        rows = await cursor.fetchall()
        stats = {"pending": 0, "active": 0, "completed": 0, "total": 0}
        for row in rows:
            stats[row[0]] = row[1]
            stats["total"] += row[1]
        return stats