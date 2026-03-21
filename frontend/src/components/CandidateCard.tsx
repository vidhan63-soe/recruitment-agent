"use client";

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

type Props = {
  candidate: Candidate;
  selected: boolean;
  checked: boolean;
  onCheck: (resumeId: string) => void;
  onPreview: (resumeId: string) => void;
};

export default function CandidateCard({
  candidate: c,
  selected,
  checked,
  onCheck,
  onPreview,
}: Props) {
  const pct = Math.round(c.final_score * 100);

  return (
    <div
      className="rounded-xl p-5 transition-all animate-in"
      style={{
        background: "var(--card)",
        border: checked
          ? "2px solid var(--accent)"
          : selected
          ? "1px solid var(--success)"
          : "1px solid var(--border)",
        animationDelay: `${c.rank * 40}ms`,
        opacity: 0,
      }}
    >
      <div className="flex items-start gap-3">
        {/* Checkbox */}
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onCheck(c.resume_id)}
          className="mt-3 w-4 h-4 rounded cursor-pointer accent-purple-600"
        />

        {/* Rank badge */}
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
          style={{
            background: selected ? "var(--success-light)" : "var(--danger-light)",
            color: selected ? "var(--success)" : "var(--danger)",
          }}
        >
          #{c.rank}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between">
            <div>
              <h3
                className="font-semibold cursor-pointer hover:underline"
                onClick={() => onPreview(c.resume_id)}
              >
                {c.candidate_name}
              </h3>
              <p className="text-xs" style={{ color: "var(--muted)" }}>
                {c.email || c.filename}
              </p>
            </div>

            <div className="text-right flex-shrink-0 ml-4">
              <div
                className="text-2xl font-bold tabular-nums"
                style={{
                  color:
                    pct >= 60 ? "var(--success)" : pct >= 45 ? "var(--warning)" : "var(--danger)",
                }}
              >
                {pct}%
              </div>
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  background: selected ? "var(--success-light)" : "var(--danger-light)",
                  color: selected ? "var(--success)" : "var(--danger)",
                }}
              >
                {selected ? "Selected" : "Rejected"}
              </span>
            </div>
          </div>

          {/* Score bars */}
          <div className="grid grid-cols-2 gap-3 my-3">
            <Bar label="Semantic" value={c.semantic_score} />
            <Bar label="LLM eval" value={c.llm_score} />
          </div>

          {c.summary && (
            <p className="text-sm leading-relaxed mb-2" style={{ color: "var(--muted)" }}>
              {c.summary}
            </p>
          )}

          <div className="flex flex-wrap gap-1.5">
            {c.matched_skills?.map((s) => (
              <span
                key={s}
                className="text-xs px-2 py-0.5 rounded-md"
                style={{ background: "var(--success-light)", color: "var(--success)" }}
              >
                {s}
              </span>
            ))}
            {c.missing_skills?.map((s) => (
              <span
                key={s}
                className="text-xs px-2 py-0.5 rounded-md line-through"
                style={{ background: "var(--danger-light)", color: "var(--danger)" }}
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Bar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span style={{ color: "var(--muted)" }}>{label}</span>
        <span className="font-medium tabular-nums">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full" style={{ background: "var(--border)" }}>
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${pct}%`,
            background: pct >= 60 ? "var(--success)" : pct >= 45 ? "var(--warning)" : "var(--danger)",
          }}
        />
      </div>
    </div>
  );
}