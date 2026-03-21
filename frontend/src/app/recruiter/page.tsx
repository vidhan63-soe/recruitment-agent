"use client";

import { useState, useEffect, useRef } from "react";
import {
  fetchHealth,
  startSession,
  getSession,
  getDashboard,
  deleteSession,
  updateCutoff,
  generateInterviewLink,
  bulkGenerateInterviews,
  generateQuestionsFromJD,
  getSessionInterviews,
  getSessionQuestions,
  generateAndSaveSessionQuestions,
  saveSessionQuestions,
  getCandidateInterviewReport,
  getAppSettings,
  updateAppSettings,
  type QuestionItem,
  type LLMProvider,
} from "@/lib/api";
import FileBrowser from "@/components/FileBrowser";
import BulkActionModal from "@/components/BulkActionModal";

type Candidate = {
  rank: number;
  resume_id: string;
  candidate_name: string;
  email: string;
  filename: string;
  semantic_score: number;
  llm_score: number;
  final_score: number;
  matched_skills: string[];
  missing_skills: string[];
  summary: string;
  status?: string;
};

type InterviewSession = {
  id: string;
  candidate_id: string;
  candidate_name: string;
  token: string;
  interview_url: string;
  status: "pending" | "active" | "completed";
  created_at: string;
  completed_at?: string;
};

type HealthData = {
  status: string;
  gpu: string;
  embedding_model: string;
  llm_model: string;
  total_resumes: number;
};

type DashboardData = {
  total_profiles: number;
  total_candidates: number;
  total_selected: number;
  total_rejected: number;
  profiles: any[];
};

type Phase = "dashboard" | "new_profile" | "processing" | "profile_view";

export default function App() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [phase, setPhase] = useState<Phase>("dashboard");
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);

  // New profile
  const [cvDir, setCvDir] = useState("");
  const [jdTitle, setJdTitle] = useState("");
  const [jdText, setJdText] = useState("");
  const [showCvBrowser, setShowCvBrowser] = useState(false);
  const [showJdBrowser, setShowJdBrowser] = useState(false);

  // Processing
  const [processLog, setProcessLog] = useState<string[]>([]);
  const [processStep, setProcessStep] = useState(0);

  // Profile view
  const [currentSessionId, setCurrentSessionId] = useState("");
  const [currentTitle, setCurrentTitle] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [totalResumes, setTotalResumes] = useState(0);
  const [liveCutoff, setLiveCutoff] = useState(0.55);

  // Actions
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [bulkActionType, setBulkActionType] = useState<"selection" | "rejection" | "">("");

  // Resume preview (right panel)
  const [activeCandidate, setActiveCandidate] = useState<Candidate | null>(null);
  const [resumeText, setResumeText] = useState("");
  const [resumeMeta, setResumeMeta] = useState<any>(null);
  const [resumeLoading, setResumeLoading] = useState(false);
  const [previewTab, setPreviewTab] = useState<"resume" | "parsed" | "interview">("resume");

  // Interview state
  const [interviewMap, setInterviewMap] = useState<Record<string, InterviewSession>>({});
  const [showInterviewModal, setShowInterviewModal] = useState(false);
  const [interviewTargets, setInterviewTargets] = useState<string[]>([]);
  const [interviewLoading, setInterviewLoading] = useState(false);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // Session question bank
  const [sessionQuestions, setSessionQuestions] = useState<QuestionItem[]>([]);
  const [showQuestionsPanel, setShowQuestionsPanel] = useState(false);

  // LLM provider setting
  const [llmProvider, setLlmProvider] = useState<LLMProvider>("auto");
  const [savingProvider, setSavingProvider] = useState(false);

  // Interview report viewer
  const [interviewReport, setInterviewReport] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(false);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null));
    loadDashboard();
    getAppSettings().then((s) => setLlmProvider(s.llm_provider)).catch(() => {});
  }, []);

  async function loadDashboard() {
    try { setDashboard(await getDashboard()); } catch {}
  }

  async function loadInterviews(sessionId: string) {
    try {
      const data = await getSessionInterviews(sessionId);
      const map: Record<string, InterviewSession> = {};
      for (const iv of data.interviews) {
        map[iv.candidate_id] = iv;
      }
      setInterviewMap(map);
    } catch {}
  }

  async function loadSessionQuestions(sessionId: string) {
    try {
      const data = await getSessionQuestions(sessionId);
      setSessionQuestions(data.questions || []);
    } catch {}
  }

  async function loadInterviewReport(candidate: Candidate) {
    setInterviewReport(null);
    setReportLoading(true);
    try {
      const data = await getCandidateInterviewReport(currentSessionId, candidate.resume_id);
      setInterviewReport(data);
    } catch {
      setInterviewReport(null);
    } finally {
      setReportLoading(false);
    }
  }

  const selected = candidates.filter((c) => c.final_score >= liveCutoff);
  const rejected = candidates.filter((c) => c.final_score < liveCutoff);

  async function openProfile(sessionId: string) {
    try {
      const data = await getSession(sessionId);
      setCandidates(data.candidates || []);
      setTotalResumes(data.total_resumes || 0);
      setCurrentTitle(data.title || "Untitled");
      setCurrentSessionId(sessionId);
      setLiveCutoff(data.cutoff_score || 0.55);
      setCheckedIds(new Set());
      setActiveCandidate(null);
      setResumeText("");
      setInterviewMap({});
      setSessionQuestions([]);
      setInterviewReport(null);
      setPhase("profile_view");
      loadInterviews(sessionId);
      loadSessionQuestions(sessionId);
    } catch (err: any) { alert("Could not load: " + err.message); }
  }

  async function viewCandidate(c: Candidate) {
    setActiveCandidate(c);
    setResumeLoading(true);
    setPreviewTab("resume");
    setInterviewReport(null);
    try {
      const res = await fetch(`http://localhost:8000/api/v1/resume/${c.resume_id}/preview`);
      const data = await res.json();
      setResumeText(data.text || "No text available");
      setResumeMeta(data.meta || null);
    } catch {
      setResumeText("Failed to load resume");
      setResumeMeta(null);
    }
    setResumeLoading(false);
  }

  async function startNewProfile() {
    if (!cvDir.trim() || !jdText.trim()) return;
    setPhase("processing");
    setProcessLog([]);
    setProcessStep(0);
    try {
      addLog("Creating recruitment profile...");
      setProcessStep(1);
      addLog(`Scanning: ${cvDir}`);
      setProcessStep(2);
      const result = await startSession(jdTitle || "Untitled Position", jdText, cvDir.trim(), 0.55);
      setProcessStep(3);
      addLog(`Processed ${result.total_resumes} resumes`);
      addLog(`${result.selected} selected, ${result.rejected} rejected`);
      setCandidates(result.candidates);
      setTotalResumes(result.total_resumes);
      setCurrentSessionId(result.session_id);
      setCurrentTitle(jdTitle || "Untitled Position");
      setLiveCutoff(0.55);
      setProcessStep(4);
      addLog("Done!");
      loadDashboard();
      setTimeout(() => { setPhase("profile_view"); setActiveCandidate(null); }, 1000);
    } catch (err: any) { addLog(`ERROR: ${err.message}`); }
  }

  function addLog(msg: string) { setProcessLog((p) => [...p, msg]); }

  function goHome() {
    setPhase("dashboard");
    setCvDir(""); setJdTitle(""); setJdText("");
    setCandidates([]); setCheckedIds(new Set());
    setActiveCandidate(null); setResumeText("");
    setInterviewMap({});
    setInterviewReport(null);
    loadDashboard();
  }

  function toggleCheck(id: string) {
    setCheckedIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }

  function selectAllInGroup(group: Candidate[]) {
    setCheckedIds((prev) => { const n = new Set(prev); group.forEach((c) => n.add(c.resume_id)); return n; });
  }

  function copyLink(url: string, token: string) {
    navigator.clipboard.writeText(url).then(() => {
      setCopiedToken(token);
      setTimeout(() => setCopiedToken(null), 2000);
    });
  }

  function openInterviewModal(targets: string[]) {
    setInterviewTargets(targets);
    setShowInterviewModal(true);
  }

  async function handleGenerateInterviews(source: "jd_generated" | "custom" | "session", customQuestions: QuestionItem[]) {
    setInterviewLoading(true);
    try {
      const opts = {
        question_source: source === "session" ? "jd_generated" : source,
        custom_questions: source === "custom" ? JSON.stringify(customQuestions) : "",
        role: currentTitle,
        difficulty: "adaptive",
      };

      if (interviewTargets.length === 1) {
        const result = await generateInterviewLink(currentSessionId, interviewTargets[0], opts);
        setInterviewMap((prev) => ({
          ...prev,
          [interviewTargets[0]]: { ...result, candidate_id: interviewTargets[0] } as any,
        }));
      } else {
        const result = await bulkGenerateInterviews(currentSessionId, interviewTargets, opts);
        const newMap = { ...interviewMap };
        for (const r of result.results) {
          newMap[r.resume_id] = r as any;
        }
        setInterviewMap(newMap);
      }
      await loadInterviews(currentSessionId);
    } catch (err: any) {
      alert("Failed to generate interview links: " + err.message);
    } finally {
      setInterviewLoading(false);
      setShowInterviewModal(false);
    }
  }

  const interviewStats = {
    total: Object.keys(interviewMap).length,
    completed: Object.values(interviewMap).filter((i) => i.status === "completed").length,
    pending: Object.values(interviewMap).filter((i) => i.status === "pending").length,
    active: Object.values(interviewMap).filter((i) => i.status === "active").length,
  };

  return (
    <div className="min-h-screen">
      {/* ═══ DASHBOARD ═══ */}
      {phase === "dashboard" && (
        <div className="max-w-5xl mx-auto px-6 py-8 animate-in">
          <header className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">RecruitAI</h1>
              <p className="text-sm" style={{ color: "var(--muted)" }}>AI-powered candidate screening & interviews</p>
            </div>
            <HealthPill health={health} />
          </header>

          {dashboard && (
            <div className="grid grid-cols-4 gap-4 mb-8">
              <StatCard label="Job profiles" value={dashboard.total_profiles} />
              <StatCard label="Total candidates" value={dashboard.total_candidates} />
              <StatCard label="Selected" value={dashboard.total_selected} color="var(--success)" />
              <StatCard label="Rejected" value={dashboard.total_rejected} color="var(--danger)" />
            </div>
          )}

          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold">Job profiles</h2>
            <button onClick={() => setPhase("new_profile")}
              className="px-6 py-2.5 rounded-xl text-sm font-semibold text-white hover:scale-105 active:scale-95 transition-transform"
              style={{ background: "var(--accent)" }}>
              + New profile
            </button>
          </div>

          {dashboard && dashboard.profiles.length > 0 ? (
            <div className="space-y-3">
              {dashboard.profiles.map((p: any) => (
                <div key={p.id} onClick={() => openProfile(p.id)}
                  className="rounded-xl p-5 cursor-pointer transition-all hover:shadow-md"
                  style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold truncate">{p.title}</h3>
                      <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                        {new Date(p.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                        {" | "}{p.total_resumes} resumes
                      </p>
                    </div>
                    <div className="flex items-center gap-4 ml-4">
                      <span className="text-sm font-semibold" style={{ color: "var(--success)" }}>{p.selected_count} selected</span>
                      <span className="text-sm" style={{ color: "var(--danger)" }}>{p.rejected_count} rejected</span>
                      <span className="text-xs px-2.5 py-1 rounded-full"
                        style={{ background: p.status === "completed" ? "var(--success-light)" : "var(--warning-light)", color: p.status === "completed" ? "var(--success)" : "var(--warning)" }}>
                        {p.status}
                      </span>
                      <button onClick={async (e) => { e.stopPropagation(); if (confirm(`Delete "${p.title}"?`)) { await deleteSession(p.id); loadDashboard(); } }}
                        className="text-xs px-2 py-1 rounded-md" style={{ color: "var(--danger)" }}>Delete</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl p-12 text-center" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <p className="font-medium mb-2">No job profiles yet</p>
              <p className="text-sm" style={{ color: "var(--muted)" }}>Create your first profile to start screening</p>
            </div>
          )}
        </div>
      )}

      {/* ═══ NEW PROFILE ═══ */}
      {phase === "new_profile" && (
        <div className="max-w-5xl mx-auto px-6 py-8 animate-in space-y-6">
          <button onClick={goHome} className="text-sm" style={{ color: "var(--muted)" }}>← Back to dashboard</button>
          <h2 className="text-lg font-semibold">Create new job profile</h2>

          <div className="rounded-xl p-6" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
            <div className="flex items-center gap-3 mb-1">
              <span className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold" style={{ background: "var(--accent-light)", color: "var(--accent)" }}>1</span>
              <h3 className="font-medium">Resume folder</h3>
            </div>
            <div className="flex gap-3 ml-10 mt-3" style={{ width: "calc(100% - 2.5rem)" }}>
              <input type="text" value={cvDir} onChange={(e) => setCvDir(e.target.value)} placeholder="C:\Users\...\CVs\Role_Name"
                className="flex-1 px-4 py-3 rounded-lg text-sm" style={{ border: "1px solid var(--border)", background: "var(--bg)" }} />
              <button onClick={() => setShowCvBrowser(true)} className="px-5 py-3 rounded-lg text-sm font-medium"
                style={{ border: "1px solid var(--accent)", color: "var(--accent)", background: "var(--accent-light)" }}>Browse</button>
            </div>
          </div>

          <div className="rounded-xl p-6" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
            <div className="flex items-center gap-3 mb-1">
              <span className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold" style={{ background: "var(--accent-light)", color: "var(--accent)" }}>2</span>
              <h3 className="font-medium">Job description</h3>
            </div>
            <div className="ml-10 mt-3" style={{ width: "calc(100% - 2.5rem)" }}>
              <div className="flex gap-3 mb-3">
                <input type="text" value={jdTitle} onChange={(e) => setJdTitle(e.target.value)} placeholder="Job title"
                  className="flex-1 px-4 py-3 rounded-lg text-sm" style={{ border: "1px solid var(--border)", background: "var(--bg)" }} />
                <button onClick={() => setShowJdBrowser(true)} className="px-5 py-3 rounded-lg text-sm font-medium whitespace-nowrap"
                  style={{ border: "1px solid var(--accent)", color: "var(--accent)", background: "var(--accent-light)" }}>Browse JD</button>
              </div>
              <textarea value={jdText} onChange={(e) => setJdText(e.target.value)} placeholder="Paste the full JD here..." rows={10}
                className="w-full px-4 py-3 rounded-lg text-sm leading-relaxed resize-y" style={{ border: "1px solid var(--border)", background: "var(--bg)" }} />
            </div>
          </div>

          <div className="flex justify-end">
            <button onClick={startNewProfile} disabled={!cvDir.trim() || !jdText.trim()}
              className="px-10 py-3 rounded-xl text-sm font-semibold text-white hover:scale-105 active:scale-95 transition-all disabled:opacity-40"
              style={{ background: "var(--accent)" }}>Start screening →</button>
          </div>

          {showCvBrowser && <FileBrowser mode="directory" onSelect={(p) => { setCvDir(p); setShowCvBrowser(false); }} onClose={() => setShowCvBrowser(false)} />}
          {showJdBrowser && <FileBrowser mode="file" fileFilter={[".pdf", ".docx", ".txt"]}
            onSelect={async (p) => { setShowJdBrowser(false); try { const r = await fetch(`http://localhost:8000/api/v1/read-file?path=${encodeURIComponent(p)}`, { method: "POST" }); if (r.ok) { const d = await r.json(); setJdText(d.text); if (!jdTitle && d.filename) setJdTitle(d.filename.replace(/\.(pdf|docx|txt)$/i, "")); } } catch {} }}
            onClose={() => setShowJdBrowser(false)} />}
        </div>
      )}

      {/* ═══ PROCESSING ═══ */}
      {phase === "processing" && (
        <div className="max-w-5xl mx-auto px-6 py-8 animate-in">
          <div className="rounded-xl p-6" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
            <h2 className="text-lg font-medium mb-4">Processing...</h2>
            <div className="flex gap-2 mb-6">
              {["Create", "Scan", "Embed", "Rank"].map((s, i) => (
                <div key={s} className="flex-1 text-center text-xs py-2 rounded-lg font-medium"
                  style={{ background: processStep > i ? "var(--success-light)" : processStep === i ? "var(--accent-light)" : "var(--bg)", color: processStep > i ? "var(--success)" : processStep === i ? "var(--accent)" : "var(--muted)" }}>
                  {processStep > i ? "✓ " : ""}{s}
                </div>
              ))}
            </div>
            <div className="rounded-lg p-4 font-mono text-xs leading-relaxed max-h-80 overflow-y-auto" style={{ background: "#1c1917", color: "#a8a29e" }}>
              {processLog.map((l, i) => <div key={i} style={{ color: l.startsWith("ERROR") ? "#ef4444" : l.startsWith("Done") ? "#22c55e" : "#a8a29e" }}>{l}</div>)}
              {processStep > 0 && processStep < 4 && <div className="animate-pulse">▌</div>}
            </div>
          </div>
        </div>
      )}

      {/* ═══ PROFILE VIEW — SPLIT PANEL ═══ */}
      {phase === "profile_view" && (
        <div className="h-screen flex flex-col">
          {/* Top bar */}
          <div className="px-6 py-3 flex items-center justify-between flex-shrink-0"
            style={{ background: "var(--card)", borderBottom: "1px solid var(--border)" }}>
            <div className="flex items-center gap-4">
              <button onClick={goHome} className="text-sm font-medium" style={{ color: "var(--accent)" }}>← Dashboard</button>
              <div>
                <h2 className="font-semibold">{currentTitle}</h2>
                <p className="text-xs" style={{ color: "var(--muted)" }}>
                  {totalResumes} resumes | {selected.length} selected | {rejected.length} rejected
                  {interviewStats.total > 0 && (
                    <span style={{ color: "var(--accent)" }}>
                      {" | "}{interviewStats.total} interviews
                      {interviewStats.completed > 0 && <span style={{ color: "var(--success)" }}> · {interviewStats.completed} done</span>}
                    </span>
                  )}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setShowQuestionsPanel(true)}
                className="text-xs px-3 py-1.5 rounded-lg font-medium flex items-center gap-1.5"
                style={{
                  background: sessionQuestions.length > 0 ? "var(--success-light)" : "var(--accent-light)",
                  color: sessionQuestions.length > 0 ? "var(--success)" : "var(--accent)",
                  border: `1px solid ${sessionQuestions.length > 0 ? "var(--success)" : "var(--accent)"}`,
                }}>
                {sessionQuestions.length > 0 ? `✓ ${sessionQuestions.length} questions` : "＋ Question bank"}
              </button>
              <span className="text-xs" style={{ color: "var(--muted)" }}>Cutoff:</span>
              <input type="range" min="0" max="100" value={Math.round(liveCutoff * 100)}
                onChange={(e) => setLiveCutoff(Number(e.target.value) / 100)} className="w-32 accent-purple-600" />
              <span className="text-sm font-semibold tabular-nums w-10">{Math.round(liveCutoff * 100)}%</span>
              <button onClick={async () => { await updateCutoff(currentSessionId, liveCutoff); loadDashboard(); }}
                className="text-xs px-3 py-1.5 rounded-lg" style={{ background: "var(--accent-light)", color: "var(--accent)" }}>Save</button>

              {/* LLM Provider toggle */}
              <div className="flex items-center gap-1.5 ml-2" style={{ borderLeft: "1px solid var(--border)", paddingLeft: 12 }}>
                <span className="text-xs" style={{ color: "var(--muted)" }}>AI:</span>
                {(["auto", "sarvam", "ollama"] as LLMProvider[]).map((p) => {
                  const labels: Record<LLMProvider, string> = { auto: "Auto", sarvam: "Sarvam", ollama: "Local" };
                  const icons: Record<LLMProvider, string> = { auto: "⚡", sarvam: "☁️", ollama: "🖥️" };
                  const active = llmProvider === p;
                  return (
                    <button
                      key={p}
                      disabled={savingProvider}
                      onClick={async () => {
                        setSavingProvider(true);
                        setLlmProvider(p);
                        await updateAppSettings({ llm_provider: p }).catch(() => {});
                        setSavingProvider(false);
                      }}
                      className="text-xs px-2.5 py-1 rounded-md font-medium transition-all"
                      style={{
                        background: active ? "var(--accent)" : "var(--accent-light)",
                        color: active ? "white" : "var(--accent)",
                        border: `1px solid ${active ? "var(--accent)" : "transparent"}`,
                        opacity: savingProvider ? 0.6 : 1,
                        cursor: savingProvider ? "not-allowed" : "pointer",
                      }}
                      title={p === "auto" ? "Try Sarvam first, fall back to Local LLM" : p === "sarvam" ? "Use Sarvam AI (cloud)" : "Use local Ollama model"}>
                      {icons[p]} {labels[p]}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Bulk action bar */}
          {checkedIds.size > 0 && (
            <div className="px-6 py-2 flex items-center justify-between flex-shrink-0"
              style={{ background: "var(--accent-light)", borderBottom: "1px solid var(--accent)" }}>
              <span className="text-sm font-medium" style={{ color: "var(--accent)" }}>{checkedIds.size} selected</span>
              <div className="flex gap-2">
                <button
                  onClick={() => openInterviewModal(Array.from(checkedIds))}
                  className="px-3 py-1 rounded-lg text-xs font-medium text-white flex items-center gap-1"
                  style={{ background: "var(--accent)" }}>
                  🎙 Generate Interviews
                </button>
                <button onClick={() => setBulkActionType("selection")} className="px-3 py-1 rounded-lg text-xs font-medium text-white" style={{ background: "var(--success)" }}>Selection email</button>
                <button onClick={() => setBulkActionType("rejection")} className="px-3 py-1 rounded-lg text-xs font-medium text-white" style={{ background: "var(--danger)" }}>Rejection email</button>
                <button onClick={() => setCheckedIds(new Set())} className="px-3 py-1 rounded-lg text-xs" style={{ border: "1px solid var(--border)" }}>Clear</button>
              </div>
            </div>
          )}

          {/* Split panels */}
          <div className="flex flex-1 overflow-hidden">
            {/* LEFT — Candidate list */}
            <div className="overflow-y-auto flex-shrink-0" style={{ width: activeCandidate ? "420px" : "100%", borderRight: activeCandidate ? "1px solid var(--border)" : "none", background: "var(--bg)", transition: "width 0.3s" }}>
              {selected.length > 0 && (
                <div className="px-4 pt-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full" style={{ background: "var(--success)" }} />
                      Selected ({selected.length})
                    </span>
                    <div className="flex items-center gap-2">
                      <button onClick={() => openInterviewModal(selected.map((c) => c.resume_id))}
                        className="text-xs px-2 py-1 rounded-lg font-medium"
                        style={{ background: "var(--accent-light)", color: "var(--accent)" }}>
                        🎙 Interview all
                      </button>
                      <button onClick={() => selectAllInGroup(selected)} className="text-xs" style={{ color: "var(--accent)" }}>Select all</button>
                    </div>
                  </div>
                  {selected.map((c) => (
                    <CandidateRow key={c.resume_id} candidate={c} isSelected={true}
                      isActive={activeCandidate?.resume_id === c.resume_id}
                      isChecked={checkedIds.has(c.resume_id)}
                      onCheck={toggleCheck}
                      onClick={() => viewCandidate(c)}
                      compact={!!activeCandidate}
                      interviewSession={interviewMap[c.resume_id]}
                      onGenerateInterview={() => openInterviewModal([c.resume_id])}
                      onCopyLink={(url, token) => copyLink(url, token)}
                      copiedToken={copiedToken}
                    />
                  ))}
                </div>
              )}

              {rejected.length > 0 && (
                <div className="px-4 pt-4 pb-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full" style={{ background: "var(--danger)" }} />
                      Rejected ({rejected.length})
                    </span>
                    <button onClick={() => selectAllInGroup(rejected)} className="text-xs" style={{ color: "var(--accent)" }}>Select all</button>
                  </div>
                  {rejected.map((c) => (
                    <CandidateRow key={c.resume_id} candidate={c} isSelected={false}
                      isActive={activeCandidate?.resume_id === c.resume_id}
                      isChecked={checkedIds.has(c.resume_id)}
                      onCheck={toggleCheck}
                      onClick={() => viewCandidate(c)}
                      compact={!!activeCandidate}
                      interviewSession={interviewMap[c.resume_id]}
                      onGenerateInterview={() => openInterviewModal([c.resume_id])}
                      onCopyLink={(url, token) => copyLink(url, token)}
                      copiedToken={copiedToken}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* RIGHT — Candidate detail panel */}
            {activeCandidate && (
              <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "var(--card)" }}>
                {/* Candidate header */}
                <div className="px-6 py-4 flex-shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-semibold">{activeCandidate.candidate_name}</h3>
                      <p className="text-sm" style={{ color: "var(--muted)" }}>
                        {activeCandidate.email || activeCandidate.filename}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <div className="text-2xl font-bold tabular-nums"
                          style={{ color: activeCandidate.final_score >= liveCutoff ? "var(--success)" : "var(--danger)" }}>
                          {Math.round(activeCandidate.final_score * 100)}%
                        </div>
                        <span className="text-xs px-2 py-0.5 rounded-full"
                          style={{ background: activeCandidate.final_score >= liveCutoff ? "var(--success-light)" : "var(--danger-light)", color: activeCandidate.final_score >= liveCutoff ? "var(--success)" : "var(--danger)" }}>
                          {activeCandidate.final_score >= liveCutoff ? "Selected" : "Rejected"}
                        </span>
                      </div>
                      <button onClick={() => { setActiveCandidate(null); setResumeText(""); setInterviewReport(null); }}
                        className="w-8 h-8 rounded-lg flex items-center justify-center text-lg" style={{ color: "var(--muted)" }}>✕</button>
                    </div>
                  </div>

                  {/* Interview link row */}
                  <div className="mt-3">
                    {interviewMap[activeCandidate.resume_id] ? (
                      <div className="flex items-center gap-2 p-2.5 rounded-lg" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
                        <span className="text-xs">🎙</span>
                        <InterviewStatusBadge status={interviewMap[activeCandidate.resume_id].status} />
                        <input readOnly value={interviewMap[activeCandidate.resume_id].interview_url}
                          className="flex-1 text-xs px-2 py-1 rounded bg-transparent"
                          style={{ border: "none", outline: "none", color: "var(--muted)", fontFamily: "monospace" }} />
                        <button
                          onClick={() => copyLink(interviewMap[activeCandidate.resume_id].interview_url, interviewMap[activeCandidate.resume_id].token)}
                          className="text-xs px-2 py-1 rounded-md font-medium"
                          style={{ background: copiedToken === interviewMap[activeCandidate.resume_id].token ? "var(--success-light)" : "var(--accent-light)", color: copiedToken === interviewMap[activeCandidate.resume_id].token ? "var(--success)" : "var(--accent)" }}>
                          {copiedToken === interviewMap[activeCandidate.resume_id].token ? "Copied!" : "Copy"}
                        </button>
                      </div>
                    ) : (
                      <button onClick={() => openInterviewModal([activeCandidate.resume_id])}
                        className="w-full py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2"
                        style={{ border: "1px dashed var(--accent)", color: "var(--accent)", background: "var(--accent-light)" }}>
                        🎙 Generate interview link
                      </button>
                    )}
                  </div>

                  {/* Score bars */}
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    <ScoreBar label="Semantic match" value={activeCandidate.semantic_score} />
                    <ScoreBar label="LLM evaluation" value={activeCandidate.llm_score} />
                  </div>

                  {activeCandidate.summary && (
                    <p className="text-sm mt-3 leading-relaxed" style={{ color: "var(--muted)" }}>{activeCandidate.summary}</p>
                  )}

                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {activeCandidate.matched_skills?.map((s) => (
                      <span key={s} className="text-xs px-2 py-0.5 rounded-md" style={{ background: "var(--success-light)", color: "var(--success)" }}>{s}</span>
                    ))}
                    {activeCandidate.missing_skills?.map((s) => (
                      <span key={s} className="text-xs px-2 py-0.5 rounded-md line-through" style={{ background: "var(--danger-light)", color: "var(--danger)" }}>{s}</span>
                    ))}
                  </div>
                </div>

                {/* Tab switcher */}
                <div className="flex gap-1 px-6 pt-3 flex-shrink-0">
                  {["resume", "parsed", "interview"].map((tab) => (
                    <button key={tab}
                      onClick={() => {
                        setPreviewTab(tab as any);
                        if (tab === "interview" && !interviewReport && !reportLoading) {
                          loadInterviewReport(activeCandidate);
                        }
                      }}
                      className="px-4 py-1.5 rounded-lg text-xs font-medium capitalize"
                      style={{ background: previewTab === tab ? "var(--accent-light)" : "transparent", color: previewTab === tab ? "var(--accent)" : "var(--muted)" }}>
                      {tab === "interview" ? "Interview Report" : tab === "resume" ? "Full resume" : "Parsed info"}
                      {tab === "interview" && interviewMap[activeCandidate.resume_id]?.status === "completed" && (
                        <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full align-middle" style={{ background: "var(--success)" }} />
                      )}
                    </button>
                  ))}
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-6 py-4">
                  {previewTab === "resume" && (
                    resumeLoading ? (
                      <div className="flex items-center justify-center h-32">
                        <p style={{ color: "var(--muted)" }}>Loading resume...</p>
                      </div>
                    ) : (
                      <pre className="text-sm leading-relaxed whitespace-pre-wrap" style={{ fontFamily: "inherit" }}>
                        {resumeText}
                      </pre>
                    )
                  )}
                  {previewTab === "parsed" && (
                    <div className="space-y-4">
                      <InfoRow label="Name" value={resumeMeta?.candidate_name || activeCandidate.candidate_name} />
                      <InfoRow label="Email" value={resumeMeta?.email || activeCandidate.email || "Not found"} />
                      <InfoRow label="Phone" value={resumeMeta?.phone || "Not found"} />
                      <InfoRow label="File" value={activeCandidate.filename} />
                      <InfoRow label="Sections" value={resumeMeta?.sections?.join(", ") || "N/A"} />
                      <InfoRow label="Chunks" value={String(resumeMeta?.chunk_count || "N/A")} />
                      <InfoRow label="Semantic score" value={`${Math.round(activeCandidate.semantic_score * 100)}%`} />
                      <InfoRow label="LLM score" value={`${Math.round(activeCandidate.llm_score * 100)}%`} />
                      <InfoRow label="Final score" value={`${Math.round(activeCandidate.final_score * 100)}%`} />
                      {activeCandidate.summary && <InfoRow label="AI Summary" value={activeCandidate.summary} />}
                    </div>
                  )}
                  {previewTab === "interview" && (
                    <InterviewReportPanel
                      interviewSession={interviewMap[activeCandidate.resume_id]}
                      report={interviewReport}
                      loading={reportLoading}
                      onRefresh={() => loadInterviewReport(activeCandidate)}
                      onReset={async () => {
                        const sess = interviewMap[activeCandidate.resume_id];
                        if (!sess) return;
                        if (!confirm("Reset this interview? The candidate will be able to retake it.")) return;
                        await fetch(`http://localhost:8000/api/interview-session/${sess.token}/reset`, { method: "POST" });
                        loadInterviewReport(activeCandidate);
                        loadDashboard();
                      }}
                    />
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Modals */}
          {bulkActionType && (
            <BulkActionModal sessionId={currentSessionId}
              candidates={candidates.filter((c) => checkedIds.has(c.resume_id))}
              actionType={bulkActionType}
              onClose={() => setBulkActionType("")}
              onDone={() => { setCheckedIds(new Set()); loadDashboard(); }} />
          )}

          {showInterviewModal && (
            <InterviewSetupModal
              sessionId={currentSessionId}
              targetCount={interviewTargets.length}
              isLoading={interviewLoading}
              sessionQuestions={sessionQuestions}
              onGenerate={handleGenerateInterviews}
              onClose={() => setShowInterviewModal(false)}
            />
          )}

          {showQuestionsPanel && (
            <SessionQuestionsPanel
              sessionId={currentSessionId}
              sessionTitle={currentTitle}
              questions={sessionQuestions}
              onSave={(qs) => { setSessionQuestions(qs); }}
              onClose={() => setShowQuestionsPanel(false)}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ── Interview Report Panel (recruiter view) ──────

function InterviewReportPanel({
  interviewSession,
  report,
  loading,
  onRefresh,
  onReset,
}: {
  interviewSession?: InterviewSession;
  report: any;
  loading: boolean;
  onRefresh: () => void;
  onReset?: () => void;
}) {
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [snapsLoading, setSnapsLoading] = useState(false);
  const [lightbox, setLightbox] = useState<string | null>(null);

  useEffect(() => {
    if (!interviewSession || interviewSession.status !== "completed") { setSnapshots([]); return; }
    setSnapsLoading(true);
    fetch(`http://localhost:8000/api/interview-session/${interviewSession.token}/snapshots`)
      .then((r) => r.json())
      .then((d) => setSnapshots(d.snapshots || []))
      .catch(() => setSnapshots([]))
      .finally(() => setSnapsLoading(false));
  }, [interviewSession?.token, interviewSession?.status]);

  if (!interviewSession) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2">
        <p className="text-sm" style={{ color: "var(--muted)" }}>No interview link generated yet.</p>
      </div>
    );
  }

  if (interviewSession.status === "pending" || interviewSession.status === "active") {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-3">
        <InterviewStatusBadge status={interviewSession.status} />
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          {interviewSession.status === "pending" ? "Candidate has not started the interview yet." : "Interview is currently in progress."}
        </p>
        <button onClick={onRefresh} className="text-xs px-3 py-1.5 rounded-lg"
          style={{ background: "var(--accent-light)", color: "var(--accent)" }}>Refresh status</button>
      </div>
    );
  }

  if (loading) {
    return <div className="flex items-center justify-center h-32"><p style={{ color: "var(--muted)" }}>Loading report...</p></div>;
  }

  if (!report || !report.report || Object.keys(report.report).length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2">
        <p className="text-sm" style={{ color: "var(--muted)" }}>Interview completed but no report submitted yet.</p>
        <button onClick={onRefresh} className="text-xs px-3 py-1.5 rounded-lg"
          style={{ background: "var(--accent-light)", color: "var(--accent)" }}>Refresh</button>
      </div>
    );
  }

  const r = report.report;
  const qa: Array<{
    question: string; answer: string; words: number;
    score?: number; feedback?: string; key_points_hit?: string[]; key_points_missed?: string[];
  }> = r.transcript || [];
  const overallScore = r.overall_score ?? "—";
  const recommendation = r.recommendation || "—";
  const duration = r.duration_minutes ?? "—";
  const integrityAlerts = r.integrity_alerts ?? 0;

  const recColor =
    typeof recommendation === "string" && recommendation.toLowerCase().includes("no hire")
      ? "var(--danger)"
      : recommendation.toLowerCase().includes("maybe")
      ? "var(--warning)"
      : "var(--success)";

  return (
    <div className="space-y-4">
      {/* Header metrics */}
      <div className="grid grid-cols-4 gap-3 p-4 rounded-xl" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
        <div className="text-center">
          <div className="text-2xl font-bold" style={{ color: "var(--accent)" }}>{overallScore}</div>
          <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>Score /10</div>
        </div>
        <div className="text-center">
          <div className="text-sm font-semibold" style={{ color: recColor }}>{recommendation}</div>
          <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>Recommendation</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold" style={{ color: "var(--text)" }}>{qa.length}</div>
          <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>Questions</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold" style={{ color: integrityAlerts > 0 ? "var(--warning)" : "var(--success)" }}>{integrityAlerts}</div>
          <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>Integrity flags</div>
        </div>
      </div>

      {/* Audio player */}
      {report.has_audio && (
        <div className="p-4 rounded-xl" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
          <p className="text-xs font-semibold mb-2" style={{ color: "var(--muted)" }}>INTERVIEW RECORDING</p>
          <audio
            controls
            src={`http://localhost:8000${report.audio_url}`}
            className="w-full"
            style={{ accentColor: "var(--accent)" }}
          />
        </div>
      )}

      {/* Integrity alerts */}
      {r.integrity_details && r.integrity_details.length > 0 && (
        <div className="p-4 rounded-xl" style={{ background: "rgba(234,179,8,0.06)", border: "1px solid rgba(234,179,8,0.3)" }}>
          <p className="text-xs font-semibold mb-2" style={{ color: "var(--warning)" }}>INTEGRITY FLAGS</p>
          {r.integrity_details.map((alert: string, i: number) => (
            <p key={i} className="text-sm" style={{ color: "var(--warning)" }}>⚠ {alert}</p>
          ))}
        </div>
      )}

      {/* Q&A Transcript */}
      {qa.length > 0 && (
        <div>
          <p className="text-xs font-semibold mb-2" style={{ color: "var(--muted)" }}>TRANSCRIPT</p>
          <div className="space-y-3">
            {qa.map((item, i) => {
              const hasScore = item.score !== undefined;
              const score = hasScore ? item.score! : Math.min(10, Math.max(1, Math.round(item.words / 15)));
              const barColor = score >= 7 ? "var(--success)" : score >= 5 ? "var(--warning)" : "var(--danger)";
              return (
                <div key={i} className="rounded-xl overflow-hidden" style={{ border: "1px solid var(--border)" }}>
                  <div className="px-4 py-2 flex items-center justify-between" style={{ background: "var(--bg)" }}>
                    <span className="text-xs font-semibold" style={{ color: "var(--accent)" }}>Q{i + 1}</span>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1.5">
                        <div className="w-20 h-1.5 rounded-full" style={{ background: "var(--border)" }}>
                          <div style={{ width: `${score * 10}%`, height: "100%", borderRadius: 9999, background: barColor }} />
                        </div>
                        <span className="text-xs font-mono" style={{ color: barColor }}>{score}/10</span>
                      </div>
                      <span className="text-xs tabular-nums" style={{ color: "var(--muted)" }}>{item.words} words</span>
                    </div>
                  </div>
                  <div className="px-4 py-3">
                    <p className="text-sm font-medium mb-2">{item.question}</p>
                    <p className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{item.answer}</p>
                    {item.feedback && (
                      <p className="text-xs mt-2 italic" style={{ color: "var(--muted)", borderLeft: "2px solid var(--accent)", paddingLeft: 8 }}>{item.feedback}</p>
                    )}
                    {((item.key_points_hit?.length ?? 0) > 0 || (item.key_points_missed?.length ?? 0) > 0) && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {(item.key_points_hit || []).map((kp, ki) => (
                          <span key={ki} className="text-xs px-1.5 py-0.5 rounded-full"
                            style={{ background: "var(--success-light)", color: "var(--success)", border: "1px solid var(--success)" }}>✓ {kp}</span>
                        ))}
                        {(item.key_points_missed || []).map((kp, ki) => (
                          <span key={ki} className="text-xs px-1.5 py-0.5 rounded-full line-through"
                            style={{ background: "var(--bg)", color: "var(--danger)", border: "1px solid var(--danger)" }}>{kp}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Snapshots */}
      {(snapsLoading || snapshots.length > 0) && (
        <div className="p-4 rounded-xl" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
          <p className="text-xs font-semibold mb-3" style={{ color: "var(--muted)" }}>
            PROCTORING SNAPSHOTS {snapshots.length > 0 && `(${snapshots.length})`}
          </p>
          {snapsLoading ? (
            <p className="text-xs" style={{ color: "var(--muted)" }}>Loading snapshots…</p>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {snapshots.map((fname) => {
                const url = `http://localhost:8000/api/interview-session/${interviewSession!.token}/snapshot/${fname}`;
                const reason = fname.split("_")[0];
                const reasonColor = reason === "face-missing" || reason === "multiple-faces" || reason === "tab-switch"
                  ? "var(--danger)" : reason === "periodic" ? "var(--muted)" : "var(--warning)";
                return (
                  <div key={fname} className="relative cursor-pointer rounded-lg overflow-hidden group"
                    style={{ border: "1px solid var(--border)", aspectRatio: "4/3" }}
                    onClick={() => setLightbox(url)}>
                    <img src={url} alt={fname} className="w-full h-full object-cover" />
                    <div className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-center"
                      style={{ background: "rgba(0,0,0,0.65)", fontSize: 9, color: reasonColor }}>
                      {reason.replace("-", " ")}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Lightbox */}
      {lightbox && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.85)" }}
          onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="snapshot" className="max-w-3xl max-h-screen rounded-xl shadow-2xl" />
        </div>
      )}

      <div className="flex justify-between items-center">
        {onReset && interviewSession?.status === "completed" && (
          <button onClick={onReset} className="text-xs px-3 py-1.5 rounded-lg"
            style={{ background: "rgba(239,68,68,0.1)", color: "var(--danger)", border: "1px solid rgba(239,68,68,0.3)" }}>
            Reset &amp; Allow Retake
          </button>
        )}
        <button onClick={onRefresh} className="text-xs px-3 py-1.5 rounded-lg ml-auto"
          style={{ background: "var(--accent-light)", color: "var(--accent)" }}>Refresh report</button>
      </div>
    </div>
  );
}

// ── Session Questions Panel ─────────────────────

function SessionQuestionsPanel({
  sessionId, sessionTitle, questions: initialQuestions, onSave, onClose,
}: {
  sessionId: string; sessionTitle: string; questions: QuestionItem[];
  onSave: (questions: QuestionItem[]) => void; onClose: () => void;
}) {
  const [questions, setQuestions] = useState<QuestionItem[]>(initialQuestions);
  const [newQ, setNewQ] = useState("");
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);

  async function handleGenerate() {
    setGenerating(true);
    try {
      const data = await generateAndSaveSessionQuestions(sessionId, sessionTitle);
      setQuestions(data.questions || []);
      onSave(data.questions || []);
    } catch (e: any) {
      alert("Generation failed: " + e.message);
    } finally { setGenerating(false); }
  }

  async function handleSave() {
    setSaving(true);
    try {
      await saveSessionQuestions(sessionId, questions);
      onSave(questions);
      onClose();
    } catch (e: any) {
      alert("Save failed: " + e.message);
    } finally { setSaving(false); }
  }

  function addQ() {
    if (newQ.trim()) {
      setQuestions((p) => [...p, { question: newQ.trim(), expected_answer: "", key_points: [] }]);
      setNewQ("");
    }
  }
  function removeQ(i: number) { setQuestions((p) => p.filter((_, idx) => idx !== i)); }

  function updateQuestion(i: number, text: string) {
    setQuestions((p) => p.map((q, idx) => idx === i ? { ...q, question: text } : q));
  }
  function updateExpected(i: number, text: string) {
    setQuestions((p) => p.map((q, idx) => idx === i ? { ...q, expected_answer: text } : q));
  }
  function updateKeyPoints(i: number, raw: string) {
    const kps = raw.split(",").map((s) => s.trim()).filter(Boolean);
    setQuestions((p) => p.map((q, idx) => idx === i ? { ...q, key_points: kps } : q));
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="rounded-2xl w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col overflow-hidden shadow-2xl"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
        <div className="px-6 py-4 flex items-center justify-between flex-shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <div>
            <h3 className="font-semibold text-base">Session Question Bank</h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
              Shared across all candidates in <strong>{sessionTitle}</strong>. Expand a question to add expected answers.
            </p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ color: "var(--muted)" }}>✕</button>
        </div>
        <div className="px-6 pt-4 flex-shrink-0 flex items-center gap-3">
          <button onClick={handleGenerate} disabled={generating}
            className="px-4 py-2 rounded-xl text-sm font-medium text-white disabled:opacity-60 flex items-center gap-2"
            style={{ background: "var(--accent)" }}>
            {generating ? <><span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />Generating…</> : "⚡ Generate from JD"}
          </button>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            {questions.length > 0 ? `${questions.length} question${questions.length !== 1 ? "s" : ""}` : "No questions yet"}
          </p>
        </div>
        <div className="px-6 py-3 flex gap-2 flex-shrink-0">
          <input type="text" value={newQ} onChange={(e) => setNewQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addQ()}
            placeholder="Add a custom question and press Enter…"
            className="flex-1 px-4 py-2.5 rounded-lg text-sm"
            style={{ border: "1px solid var(--border)", background: "var(--bg)" }} />
          <button onClick={addQ} className="px-4 py-2.5 rounded-lg text-sm font-medium text-white" style={{ background: "var(--accent)" }}>Add</button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 pb-4 space-y-2">
          {questions.length === 0 ? (
            <p className="text-xs text-center py-10" style={{ color: "var(--muted)" }}>No questions yet.</p>
          ) : questions.map((item, i) => (
            <div key={i} className="rounded-lg overflow-hidden"
              style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
              {/* Question row */}
              <div className="flex gap-2 items-start p-3 group">
                <span className="text-xs font-bold w-5 mt-0.5 flex-shrink-0" style={{ color: "var(--accent)" }}>Q{i + 1}</span>
                <input
                  value={item.question}
                  onChange={(e) => updateQuestion(i, e.target.value)}
                  className="flex-1 bg-transparent text-sm leading-relaxed outline-none"
                  style={{ color: "var(--text)" }}
                />
                <div className="flex gap-1 flex-shrink-0">
                  <button
                    onClick={() => setExpandedIdx(expandedIdx === i ? null : i)}
                    className="text-xs px-2 py-0.5 rounded transition-colors"
                    style={{
                      background: expandedIdx === i ? "var(--accent-light)" : "transparent",
                      color: expandedIdx === i ? "var(--accent)" : "var(--muted)",
                      border: "1px solid " + (expandedIdx === i ? "var(--accent)" : "var(--border)"),
                    }}
                    title="Add expected answer">
                    {item.expected_answer ? "★ Answer" : "+ Answer"}
                  </button>
                  <button onClick={() => removeQ(i)} className="text-xs px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: "var(--danger)" }}>✕</button>
                </div>
              </div>
              {/* Expanded: expected answer + key points */}
              {expandedIdx === i && (
                <div className="px-3 pb-3 space-y-2" style={{ borderTop: "1px solid var(--border)" }}>
                  <div className="pt-2">
                    <label className="text-xs font-medium block mb-1" style={{ color: "var(--muted)" }}>
                      Expected answer <span style={{ color: "var(--muted)", fontWeight: 400 }}>(describe what a strong answer should cover)</span>
                    </label>
                    <textarea
                      value={item.expected_answer}
                      onChange={(e) => updateExpected(i, e.target.value)}
                      rows={3}
                      placeholder="e.g. Candidate should mention X and demonstrate understanding of Y…"
                      className="w-full px-3 py-2 rounded-lg text-sm resize-none"
                      style={{ border: "1px solid var(--border)", background: "var(--card)", color: "var(--text)" }}
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium block mb-1" style={{ color: "var(--muted)" }}>
                      Key points <span style={{ color: "var(--muted)", fontWeight: 400 }}>(comma-separated keywords to check)</span>
                    </label>
                    <input
                      value={(item.key_points || []).join(", ")}
                      onChange={(e) => updateKeyPoints(i, e.target.value)}
                      placeholder="e.g. asyncio, event loop, async/await, production usage"
                      className="w-full px-3 py-2 rounded-lg text-sm"
                      style={{ border: "1px solid var(--border)", background: "var(--card)", color: "var(--text)" }}
                    />
                    {item.key_points && item.key_points.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {item.key_points.map((kp, ki) => (
                          <span key={ki} className="text-xs px-2 py-0.5 rounded-full"
                            style={{ background: "var(--accent-light)", color: "var(--accent)" }}>
                            {kp}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="px-6 py-4 flex justify-end gap-2 flex-shrink-0" style={{ borderTop: "1px solid var(--border)" }}>
          <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm" style={{ border: "1px solid var(--border)" }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || questions.length === 0}
            className="px-6 py-2 rounded-xl text-sm font-semibold text-white disabled:opacity-50"
            style={{ background: "var(--success)" }}>
            {saving ? "Saving…" : `Save ${questions.length} question${questions.length !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Interview Status Badge ──────────────────────

function InterviewStatusBadge({ status }: { status: string }) {
  const config = {
    pending: { label: "Pending", bg: "var(--warning-light)", color: "var(--warning)" },
    active: { label: "In Progress", bg: "var(--accent-light)", color: "var(--accent)" },
    completed: { label: "Completed", bg: "var(--success-light)", color: "var(--success)" },
  }[status] || { label: status, bg: "var(--bg)", color: "var(--muted)" };

  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap"
      style={{ background: config.bg, color: config.color }}>
      {config.label}
    </span>
  );
}

// ── Interview Setup Modal ────────────────────────

function InterviewSetupModal({
  sessionId, targetCount, isLoading, sessionQuestions, onGenerate, onClose,
}: {
  sessionId: string; targetCount: number; isLoading: boolean;
  sessionQuestions: QuestionItem[];
  onGenerate: (source: "jd_generated" | "custom" | "session", questions: QuestionItem[]) => void;
  onClose: () => void;
}) {
  const hasSessionQs = sessionQuestions.length > 0;
  const [source, setSource] = useState<"session" | "jd_generated" | "custom">(hasSessionQs ? "session" : "jd_generated");
  const [questions, setQuestions] = useState<QuestionItem[]>(hasSessionQs ? [...sessionQuestions] : []);
  const [loadingQuestions, setLoadingQuestions] = useState(false);
  const [newQuestion, setNewQuestion] = useState("");

  async function fetchGeneratedQuestions() {
    setLoadingQuestions(true);
    try { const data = await generateQuestionsFromJD(sessionId); setQuestions(data.questions || []); }
    catch { alert("Could not generate questions."); }
    finally { setLoadingQuestions(false); }
  }

  function handleSourceChange(s: "session" | "jd_generated" | "custom") {
    setSource(s);
    if (s === "session") setQuestions([...sessionQuestions]);
    else if (s !== "custom") setQuestions([]);
  }

  function addQuestion() {
    if (newQuestion.trim()) {
      setQuestions((prev) => [...prev, { question: newQuestion.trim(), expected_answer: "", key_points: [] }]);
      setNewQuestion("");
    }
  }
  function removeQuestion(i: number) { setQuestions((prev) => prev.filter((_, idx) => idx !== i)); }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div className="rounded-2xl w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col overflow-hidden shadow-2xl"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
        <div className="px-6 py-4 flex items-center justify-between flex-shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <div>
            <h3 className="font-semibold text-base">Generate Interview Links</h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
              {targetCount === 1 ? "1 candidate" : `${targetCount} candidates`} will receive a unique interview link
            </p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ color: "var(--muted)" }}>✕</button>
        </div>
        <div className="px-6 py-4 flex-shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="text-xs font-medium mb-3" style={{ color: "var(--muted)" }}>Question source</p>
          <div className="flex gap-2">
            {hasSessionQs && (
              <button onClick={() => handleSourceChange("session")} className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-all"
                style={{ background: source === "session" ? "var(--success)" : "var(--bg)", color: source === "session" ? "white" : "var(--muted)", border: "1px solid " + (source === "session" ? "var(--success)" : "var(--border)") }}>
                ✓ Session bank ({sessionQuestions.length})
              </button>
            )}
            <button onClick={() => handleSourceChange("jd_generated")} className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-all"
              style={{ background: source === "jd_generated" ? "var(--accent)" : "var(--bg)", color: source === "jd_generated" ? "white" : "var(--muted)", border: "1px solid " + (source === "jd_generated" ? "var(--accent)" : "var(--border)") }}>
              Auto-generate from JD
            </button>
            <button onClick={() => handleSourceChange("custom")} className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-all"
              style={{ background: source === "custom" ? "var(--accent)" : "var(--bg)", color: source === "custom" ? "white" : "var(--muted)", border: "1px solid " + (source === "custom" ? "var(--accent)" : "var(--border)") }}>
              Custom questions
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {source === "session" && questions.map((q, i) => (
            <div key={i} className="p-3 rounded-lg" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
              <div className="flex gap-2 items-start">
                <span className="text-xs font-bold w-5 mt-0.5 flex-shrink-0" style={{ color: "var(--success)" }}>Q{i + 1}</span>
                <p className="text-sm flex-1 leading-relaxed">{q.question}</p>
              </div>
              {q.expected_answer && (
                <p className="text-xs mt-1.5 ml-7 italic" style={{ color: "var(--muted)" }}>
                  Expected: {q.expected_answer.slice(0, 120)}{q.expected_answer.length > 120 ? "…" : ""}
                </p>
              )}
              {q.key_points && q.key_points.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5 ml-7">
                  {q.key_points.map((kp, ki) => (
                    <span key={ki} className="text-xs px-1.5 py-0.5 rounded-full"
                      style={{ background: "var(--accent-light)", color: "var(--accent)" }}>{kp}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {source === "jd_generated" && questions.length === 0 && (
            <div className="text-center py-8">
              <p className="text-sm mb-4" style={{ color: "var(--muted)" }}>Questions generated from JD when links are created.</p>
              <button onClick={fetchGeneratedQuestions} disabled={loadingQuestions}
                className="px-6 py-2.5 rounded-xl text-sm font-medium text-white disabled:opacity-60"
                style={{ background: "var(--accent)" }}>
                {loadingQuestions ? "Generating..." : "Preview questions"}
              </button>
            </div>
          )}
          {source === "jd_generated" && questions.length > 0 && questions.map((q, i) => (
            <div key={i} className="flex gap-2 items-start p-3 rounded-lg" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
              <span className="text-xs font-bold w-5 mt-0.5 flex-shrink-0" style={{ color: "var(--accent)" }}>Q{i + 1}</span>
              <p className="text-sm flex-1 leading-relaxed">{q.question}</p>
              <button onClick={() => removeQuestion(i)} className="text-xs flex-shrink-0" style={{ color: "var(--danger)" }}>✕</button>
            </div>
          ))}
          {source === "custom" && (
            <>
              <div className="flex gap-2">
                <input type="text" value={newQuestion} onChange={(e) => setNewQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addQuestion()}
                  placeholder="Type a question and press Enter..."
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm"
                  style={{ border: "1px solid var(--border)", background: "var(--bg)" }} />
                <button onClick={addQuestion} className="px-4 py-2.5 rounded-lg text-sm font-medium text-white" style={{ background: "var(--accent)" }}>Add</button>
              </div>
              {questions.length === 0 ? (
                <p className="text-xs text-center py-6" style={{ color: "var(--muted)" }}>No questions yet.</p>
              ) : questions.map((q, i) => (
                <div key={i} className="flex gap-2 items-start p-3 rounded-lg" style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
                  <span className="text-xs font-bold w-5 mt-0.5 flex-shrink-0" style={{ color: "var(--accent)" }}>Q{i + 1}</span>
                  <p className="text-sm flex-1 leading-relaxed">{q.question}</p>
                  <button onClick={() => removeQuestion(i)} className="text-xs flex-shrink-0" style={{ color: "var(--danger)" }}>✕</button>
                </div>
              ))}
            </>
          )}
        </div>
        <div className="px-6 py-4 flex items-center justify-between flex-shrink-0" style={{ borderTop: "1px solid var(--border)" }}>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            {source === "session" ? `${questions.length} pre-saved questions — instant` :
             source === "jd_generated" ? "Generated at link creation time" :
             `${questions.length} custom question${questions.length !== 1 ? "s" : ""}`}
          </p>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded-xl text-sm" style={{ border: "1px solid var(--border)" }}>Cancel</button>
            <button
              onClick={() => onGenerate(source, questions)}
              disabled={isLoading || (source === "custom" && questions.length === 0) || (source === "session" && questions.length === 0)}
              className="px-6 py-2 rounded-xl text-sm font-semibold text-white disabled:opacity-50 flex items-center gap-2"
              style={{ background: "var(--accent)" }}>
              {isLoading ? <><span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />Generating...</> : `Generate ${targetCount > 1 ? `${targetCount} links` : "link"}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Candidate Row ───────────────────────────────

function CandidateRow({ candidate: c, isSelected, isActive, isChecked, onCheck, onClick, compact, interviewSession, onGenerateInterview, onCopyLink, copiedToken }: {
  candidate: Candidate; isSelected: boolean; isActive: boolean; isChecked: boolean;
  onCheck: (id: string) => void; onClick: () => void; compact: boolean;
  interviewSession?: InterviewSession;
  onGenerateInterview: () => void;
  onCopyLink: (url: string, token: string) => void;
  copiedToken: string | null;
}) {
  const pct = Math.round(c.final_score * 100);
  return (
    <div className="rounded-lg px-3 py-2.5 mb-1.5 transition-all"
      style={{ background: isActive ? "var(--accent-light)" : "var(--card)", border: isActive ? "1px solid var(--accent)" : "1px solid var(--border)" }}>
      <div className="flex items-center gap-2.5">
        <input type="checkbox" checked={isChecked} onChange={() => onCheck(c.resume_id)} className="w-3.5 h-3.5 rounded accent-purple-600 flex-shrink-0" />
        <div className="flex-1 min-w-0 cursor-pointer" onClick={onClick}>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium truncate">{c.candidate_name}</span>
            <span className="text-sm font-bold tabular-nums ml-2 flex-shrink-0"
              style={{ color: pct >= 55 ? "var(--success)" : pct >= 40 ? "var(--warning)" : "var(--danger)" }}>{pct}%</span>
          </div>
          {!compact && <p className="text-xs truncate mt-0.5" style={{ color: "var(--muted)" }}>{c.email || c.filename}</p>}
        </div>
      </div>
      {!compact && (
        <div className="mt-2 ml-6">
          {interviewSession ? (
            <div className="flex items-center gap-1.5">
              <InterviewStatusBadge status={interviewSession.status} />
              <button onClick={(e) => { e.stopPropagation(); onCopyLink(interviewSession.interview_url, interviewSession.token); }}
                className="text-xs px-2 py-0.5 rounded-md font-medium flex-shrink-0"
                style={{ background: copiedToken === interviewSession.token ? "var(--success-light)" : "var(--bg)", color: copiedToken === interviewSession.token ? "var(--success)" : "var(--muted)", border: "1px solid var(--border)" }}>
                {copiedToken === interviewSession.token ? "✓ Copied" : "Copy link"}
              </button>
              <a href={interviewSession.interview_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                className="text-xs px-2 py-0.5 rounded-md font-medium"
                style={{ background: "var(--accent-light)", color: "var(--accent)", border: "1px solid var(--accent)" }}>
                Open ↗
              </a>
            </div>
          ) : isSelected ? (
            <button onClick={(e) => { e.stopPropagation(); onGenerateInterview(); }}
              className="text-xs px-2 py-0.5 rounded-md font-medium"
              style={{ color: "var(--accent)", border: "1px dashed var(--accent)", background: "transparent" }}>
              + Generate interview link
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ── Small components ────────────────────────────

function HealthPill({ health }: { health: HealthData | null }) {
  if (!health) return <div className="text-xs px-3 py-1.5 rounded-full" style={{ background: "var(--danger-light)", color: "var(--danger)" }}>Backend offline</div>;
  return (
    <div className="flex items-center gap-3 text-xs px-4 py-2 rounded-full" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
      <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{ background: "var(--success)" }} />Online</span>
      <span style={{ color: "var(--muted)" }}>{health.gpu === "none" ? "CPU" : "GPU"}</span>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="rounded-xl px-5 py-4" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
      <p className="text-xs mb-1" style={{ color: "var(--muted)" }}>{label}</p>
      <p className="text-2xl font-bold tabular-nums" style={{ color: color || "var(--text)" }}>{value}</p>
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span style={{ color: "var(--muted)" }}>{label}</span>
        <span className="font-medium tabular-nums">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full" style={{ background: "var(--border)" }}>
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: pct >= 60 ? "var(--success)" : pct >= 45 ? "var(--warning)" : "var(--danger)" }} />
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex" style={{ borderBottom: "1px solid var(--border)", paddingBottom: "12px" }}>
      <span className="text-sm w-32 flex-shrink-0" style={{ color: "var(--muted)" }}>{label}</span>
      <span className="text-sm flex-1">{value}</span>
    </div>
  );
}
