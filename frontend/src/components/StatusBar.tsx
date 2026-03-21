"use client";

type Props = {
  health: {
    status: string;
    gpu: string;
    embedding_model: string;
    llm_model: string;
    total_resumes: number;
  } | null;
  resumeCount: number;
};

export default function StatusBar({ health, resumeCount }: Props) {
  if (!health) {
    return (
      <div
        className="rounded-lg px-4 py-3 mb-6 text-sm"
        style={{ background: "var(--danger-light)", color: "var(--danger)" }}
      >
        Backend not connected — make sure{" "}
        <code className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ background: "rgba(0,0,0,0.06)" }}>
          python app.py
        </code>{" "}
        is running on port 8000
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap gap-4 rounded-lg px-5 py-3 mb-6 text-xs"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <Chip label="Status" value="Online" color="var(--success)" />
      <Chip label="GPU" value={health.gpu === "none" ? "CPU mode" : health.gpu} />
      <Chip label="Embedder" value={health.embedding_model} />
      <Chip label="LLM" value={health.llm_model} />
      <Chip label="Resumes" value={String(resumeCount)} />
    </div>
  );
}

function Chip({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ color: "var(--muted)" }}>{label}:</span>
      <span className="font-medium" style={{ color: color || "var(--text)" }}>
        {value}
      </span>
    </div>
  );
}
