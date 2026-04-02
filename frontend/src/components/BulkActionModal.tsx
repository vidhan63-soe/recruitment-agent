"use client";

import { useState, useEffect } from "react";
import { getTemplates, bulkAction } from "@/lib/api";

type Candidate = {
  resume_id: string;
  candidate_name: string;
  email: string;
  status?: string;
};

type Props = {
  sessionId: string;
  candidates: Candidate[];
  actionType: "selection" | "rejection";
  onClose: () => void;
  onDone: () => void;
};

export default function BulkActionModal({
  sessionId,
  candidates,
  actionType,
  onClose,
  onDone,
}: Props) {
  const [templates, setTemplates] = useState<any[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null);
  const [vars, setVars] = useState<Record<string, string>>({
    company_name: "",
    recruiter_name: "",
    interview_mode: "Virtual (Google Meet)",
    interview_date: "",
    assessment_link: "",
    deadline: "",
    duration: "60 minutes",
  });
  const [previewBody, setPreviewBody] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    getTemplates(actionType).then(setTemplates);
  }, [actionType]);

  useEffect(() => {
    if (!selectedTemplate) return;
    let body = selectedTemplate.body;
    body = body.replace(/\{\{candidate_name\}\}/g, candidates[0]?.candidate_name || "Candidate");
    for (const [k, v] of Object.entries(vars)) {
      body = body.replace(new RegExp(`\\{\\{${k}\\}\\}`, "g"), v || `[${k}]`);
    }
    setPreviewBody(body);
  }, [selectedTemplate, vars, candidates]);

  async function handleSend() {
    if (!selectedTemplate) return;
    setSending(true);
    try {
      const res = await bulkAction(
        sessionId,
        "send_email",
        candidates.map((c) => c.resume_id),
        selectedTemplate.id,
        vars
      );
      setResult(res);
    } catch (err: any) {
      alert(err.message);
    }
    setSending(false);
  }

  const emailCount = candidates.filter((c) => c.email).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.4)" }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl w-full max-w-3xl max-h-[90vh] flex flex-col"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-6 py-4 flex items-center justify-between"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div>
            <h3 className="font-semibold">
              {actionType === "selection" ? "Send selection emails" : "Send rejection emails"}
            </h3>
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              {candidates.length} candidates | {emailCount} with email addresses
            </p>
          </div>
          <button onClick={onClose} className="text-lg" style={{ color: "var(--muted)" }}>
            x
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {result ? (
            /* Results */
            <div>
              <div
                className="rounded-lg px-4 py-3 mb-4 text-sm"
                style={{
                  background: "var(--success-light)",
                  color: "var(--success)",
                }}
              >
                {result.total} emails queued successfully!
              </div>
              <div className="space-y-2">
                {result.results?.map((r: any, i: number) => (
                  <div
                    key={i}
                    className="text-sm px-4 py-2 rounded-lg"
                    style={{ background: "var(--bg)" }}
                  >
                    <span className="font-medium">{r.candidate}</span>
                    <span className="ml-2" style={{ color: "var(--muted)" }}>
                      {r.email || "no email"}
                    </span>
                    <span
                      className="ml-2 text-xs px-2 py-0.5 rounded-full"
                      style={{
                        background: "var(--success-light)",
                        color: "var(--success)",
                      }}
                    >
                      {r.status}
                    </span>
                  </div>
                ))}
              </div>
              <button
                onClick={() => { onDone(); onClose(); }}
                className="mt-4 px-6 py-2 rounded-lg text-sm font-medium text-white"
                style={{ background: "var(--accent)" }}
              >
                Done
              </button>
            </div>
          ) : (
            <>
              {/* Template selector */}
              <div>
                <label className="text-sm font-medium block mb-2">
                  Email template
                </label>
                <div className="space-y-2">
                  {templates.map((t) => (
                    <div
                      key={t.id}
                      className="px-4 py-3 rounded-lg cursor-pointer text-sm transition-colors"
                      style={{
                        background:
                          selectedTemplate?.id === t.id
                            ? "var(--accent-light)"
                            : "var(--bg)",
                        border:
                          selectedTemplate?.id === t.id
                            ? "1px solid var(--accent)"
                            : "1px solid var(--border)",
                      }}
                      onClick={() => setSelectedTemplate(t)}
                    >
                      <span className="font-medium">{t.name}</span>
                      <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
                        Subject: {t.subject}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              {selectedTemplate && (
                <>
                  {/* Template variables */}
                  <div>
                    <label className="text-sm font-medium block mb-2">
                      Fill in details
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      {Object.entries(vars).map(([key, val]) => (
                        <div key={key}>
                          <label
                            className="text-xs block mb-1"
                            style={{ color: "var(--muted)" }}
                          >
                            {key.replace(/_/g, " ")}
                          </label>
                          <input
                            type="text"
                            value={val}
                            onChange={(e) =>
                              setVars({ ...vars, [key]: e.target.value })
                            }
                            className="w-full px-3 py-2 rounded-lg text-sm"
                            style={{
                              border: "1px solid var(--border)",
                              background: "var(--bg)",
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Preview */}
                  <div>
                    <label className="text-sm font-medium block mb-2">
                      Preview (first candidate)
                    </label>
                    <div
                      className="rounded-lg px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto"
                      style={{
                        background: "var(--bg)",
                        border: "1px solid var(--border)",
                        color: "var(--muted)",
                      }}
                    >
                      {previewBody}
                    </div>
                  </div>

                  {/* Send button */}
                  <div className="flex items-center justify-between pt-2">
                    <p className="text-xs" style={{ color: "var(--muted)" }}>
                      Emails will be queued (SMTP sending in Phase 2)
                    </p>
                    <button
                      onClick={handleSend}
                      disabled={sending}
                      className="px-8 py-2.5 rounded-lg text-sm font-medium text-white disabled:opacity-50"
                      style={{ background: "var(--accent)" }}
                    >
                      {sending
                        ? "Sending..."
                        : `Queue ${candidates.length} emails`}
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}