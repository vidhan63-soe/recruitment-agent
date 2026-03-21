const API = "/api/v1";

export async function fetchHealth() {
  const res = await fetch(`${API}/health`);
  if (!res.ok) throw new Error("Backend offline");
  return res.json();
}

export async function scanDirectory(directory: string) {
  const res = await fetch(`${API}/resumes/scan-directory?directory=${encodeURIComponent(directory)}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function matchJD(jdText: string, jdTitle: string, topK = 10) {
  const res = await fetch(`${API}/match`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jd_text: jdText, jd_title: jdTitle, top_k: topK, min_score: 0.3 }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function listResumes() {
  const res = await fetch(`${API}/resumes`);
  if (!res.ok) throw new Error("Failed to list resumes");
  return res.json();
}

export async function deleteAllResumes() {
  const res = await fetch(`${API}/resumes`, { method: "DELETE" });
  return res.json();
}

export async function startSession(
  title: string,
  jdText: string,
  cvDirectory: string,
  cutoffScore = 0.55
) {
  const params = new URLSearchParams({
    title,
    jd_text: jdText,
    cv_directory: cvDirectory,
    cutoff_score: String(cutoffScore),
  });
  const res = await fetch(`${API}/sessions/start?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function listSessions() {
  const res = await fetch(`${API}/sessions`);
  if (!res.ok) throw new Error("Failed to list sessions");
  return res.json();
}

export async function getSession(sessionId: string) {
  const res = await fetch(`${API}/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Session not found");
  return res.json();
}

export async function deleteSession(sessionId: string) {
  const res = await fetch(`${API}/sessions/${sessionId}`, { method: "DELETE" });
  return res.json();
}

export async function changeCandidateStatus(
  sessionId: string,
  resumeId: string,
  status: string
) {
  const res = await fetch(
    `${API}/sessions/${sessionId}/candidates/${resumeId}/status?status=${status}`,
    { method: "POST" }
  );
  return res.json();
}

export async function previewResume(resumeId: string) {
  const res = await fetch(`${API}/resume/${resumeId}/preview`);
  if (!res.ok) throw new Error("Resume not found");
  return res.json();
}

export async function getTemplates(type = "") {
  const res = await fetch(`${API}/templates?template_type=${type}`);
  return res.json();
}

export async function bulkAction(
  sessionId: string,
  action: string,
  resumeIds: string[],
  templateId = 0,
  templateVars: Record<string, string> = {}
) {
  const params = new URLSearchParams({
    action,
    resume_ids: resumeIds.join(","),
    template_id: String(templateId),
    template_vars: JSON.stringify(templateVars),
  });
  const res = await fetch(`${API}/sessions/${sessionId}/bulk-action?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed" }));
    throw new Error(err.detail);
  }
  return res.json();
}

export async function updateCutoff(sessionId: string, cutoff: number) {
  const res = await fetch(
    `${API}/sessions/${sessionId}/update-cutoff?cutoff_score=${cutoff}`,
    { method: "POST" }
  );
  return res.json();
}

export async function getSessionEmails(sessionId: string) {
  const res = await fetch(`${API}/sessions/${sessionId}/emails`);
  return res.json();
}

export async function getDashboard() {
  const res = await fetch(`${API}/dashboard`);
  if (!res.ok) throw new Error("Failed to load dashboard");
  return res.json();
}

// ── Interview Agent API ──────────────────────

export async function generateQuestionsFromJD(
  sessionId: string,
  role = "",
  numQuestions = 8
) {
  const params = new URLSearchParams({ role, num_questions: String(numQuestions) });
  const res = await fetch(`${API}/sessions/${sessionId}/generate-questions?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function generateInterviewLink(
  sessionId: string,
  resumeId: string,
  options: { question_source?: string; custom_questions?: string; role?: string; difficulty?: string } = {}
) {
  const params = new URLSearchParams({
    question_source: options.question_source || "jd_generated",
    custom_questions: options.custom_questions || "",
    role: options.role || "",
    difficulty: options.difficulty || "adaptive",
  });
  const res = await fetch(
    `${API}/sessions/${sessionId}/candidates/${resumeId}/generate-interview?${params}`,
    { method: "POST" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function bulkGenerateInterviews(
  sessionId: string,
  resumeIds: string[],
  options: { question_source?: string; custom_questions?: string; role?: string; difficulty?: string } = {}
) {
  const params = new URLSearchParams({
    resume_ids: resumeIds.join(","),
    question_source: options.question_source || "jd_generated",
    custom_questions: options.custom_questions || "",
    role: options.role || "",
    difficulty: options.difficulty || "adaptive",
  });
  const res = await fetch(
    `${API}/sessions/${sessionId}/bulk-generate-interviews?${params}`,
    { method: "POST" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function getSessionInterviews(sessionId: string) {
  const res = await fetch(`${API}/sessions/${sessionId}/interviews`);
  if (!res.ok) throw new Error("Failed to load interviews");
  return res.json();
}

// ── Session Question Bank ────────────────────────

export type QuestionItem = {
  question: string;
  expected_answer: string;
  key_points: string[];
};

export type QuestionScore = {
  score: number;
  feedback: string;
  key_points_hit: string[];
  key_points_missed: string[];
};

export async function getSessionQuestions(sessionId: string): Promise<{ questions: QuestionItem[]; count: number }> {
  const res = await fetch(`${API}/sessions/${sessionId}/questions`);
  if (!res.ok) throw new Error("Failed to load questions");
  return res.json();
}

export async function generateAndSaveSessionQuestions(
  sessionId: string,
  role = "",
  numQuestions = 8
): Promise<{ questions: QuestionItem[]; count: number; saved: boolean }> {
  const params = new URLSearchParams({ role, num_questions: String(numQuestions) });
  const res = await fetch(`${API}/sessions/${sessionId}/questions/generate?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

export async function saveSessionQuestions(sessionId: string, questions: QuestionItem[]) {
  const res = await fetch(`${API}/sessions/${sessionId}/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ questions }),
  });
  if (!res.ok) throw new Error("Failed to save questions");
  return res.json();
}

// ── Interview Report (recruiter view) ────────────

export async function getCandidateInterviewReport(sessionId: string, resumeId: string) {
  const res = await fetch(`${API}/sessions/${sessionId}/candidates/${resumeId}/interview-report`);
  if (!res.ok) throw new Error("No interview report found");
  return res.json();
}

// ── Candidate-side submission ─────────────────────

export async function submitInterviewReport(token: string, report: object) {
  const res = await fetch(`/api/interview-session/${token}/submit-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report }),
  });
  if (!res.ok) throw new Error("Failed to submit report");
  return res.json();
}

export async function uploadInterviewAudio(token: string, audioBlob: Blob) {
  const res = await fetch(`/api/interview-session/${token}/audio`, {
    method: "POST",
    headers: { "Content-Type": "audio/webm" },
    body: audioBlob,
  });
  if (!res.ok) throw new Error("Failed to upload audio");
  return res.json();
}

// ── App Settings ──────────────────────────────────────────────────

export type LLMProvider = "auto" | "sarvam" | "ollama";

export async function getAppSettings(): Promise<{ llm_provider: LLMProvider }> {
  const res = await fetch(`${API}/settings`);
  if (!res.ok) return { llm_provider: "auto" };
  return res.json();
}

export async function updateAppSettings(settings: { llm_provider: LLMProvider }): Promise<void> {
  await fetch(`${API}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}