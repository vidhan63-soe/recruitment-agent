"use client";

import { useState, useEffect } from "react";

type Props = {
  resumeId: string;
  onClose: () => void;
};

export default function ResumePreview({ resumeId, onClose }: Props) {
  const [data, setData] = useState<{ meta: any; text: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`http://localhost:8000/api/v1/resume/${resumeId}/preview`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [resumeId]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.4)" }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-6 py-4 flex items-center justify-between"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div>
            <h3 className="font-semibold">
              {data?.meta?.candidate_name || "Resume"}
            </h3>
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              {data?.meta?.filename} | {data?.meta?.chunk_count} chunks |{" "}
              Sections: {data?.meta?.sections?.join(", ")}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-lg"
            style={{ color: "var(--muted)" }}
          >
            x
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <p style={{ color: "var(--muted)" }}>Loading...</p>
          ) : data?.text ? (
            <pre
              className="text-sm leading-relaxed whitespace-pre-wrap"
              style={{ fontFamily: "inherit", color: "var(--text)" }}
            >
              {data.text}
            </pre>
          ) : (
            <p style={{ color: "var(--danger)" }}>Could not load resume</p>
          )}
        </div>
      </div>
    </div>
  );
}