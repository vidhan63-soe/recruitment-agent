"use client";

import { useState, useEffect } from "react";

type BrowseItem = {
  name: string;
  path: string;
  type: "folder" | "file";
  ext?: string;
  size?: number;
};

type Props = {
  mode: "directory" | "file";
  fileFilter?: string[];
  onSelect: (path: string) => void;
  onClose: () => void;
};

export default function FileBrowser({ mode, fileFilter, onSelect, onClose }: Props) {
  const [currentPath, setCurrentPath] = useState("");
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [items, setItems] = useState<BrowseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    browse(currentPath);
  }, []);

  async function browse(path: string) {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/v1/browse?path=${encodeURIComponent(path)}`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed" }));
        throw new Error(err.detail);
      }
      const data = await res.json();
      setCurrentPath(data.current);
      setParentPath(data.parent);

      let filtered = data.items as BrowseItem[];
      if (mode === "file" && fileFilter) {
        filtered = filtered.filter(
          (item) =>
            item.type === "folder" ||
            (item.ext && fileFilter.includes(item.ext))
        );
      }
      setItems(filtered);
    } catch (err: any) {
      setError(err.message);
    }
    setLoading(false);
  }

  function handleItemClick(item: BrowseItem) {
    if (item.type === "folder") {
      browse(item.path);
    } else if (mode === "file") {
      onSelect(item.path);
    }
  }

  const folderCount = items.filter((i) => i.type === "folder").length;
  const fileCount = items.filter((i) => i.type === "file").length;
  const resumeCount = items.filter(
    (i) => i.type === "file" && (i.ext === ".pdf" || i.ext === ".docx")
  ).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.4)" }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl w-full max-w-xl max-h-[80vh] flex flex-col"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-5 py-4 flex items-center justify-between"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div>
            <h3 className="font-semibold">
              {mode === "directory" ? "Select resume folder" : "Select JD file"}
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
              {mode === "directory"
                ? "Navigate to the folder containing your CVs"
                : "Pick a .pdf, .docx, or .txt file"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-lg"
            style={{ color: "var(--muted)" }}
          >
            ×
          </button>
        </div>

        {/* Path breadcrumb */}
        <div
          className="px-5 py-2 text-xs font-mono flex items-center gap-2"
          style={{ background: "var(--bg)", color: "var(--muted)" }}
        >
          <span className="truncate flex-1">{currentPath}</span>
          {mode === "directory" && resumeCount > 0 && (
            <span
              className="px-2 py-0.5 rounded-full text-xs whitespace-nowrap"
              style={{ background: "var(--success-light)", color: "var(--success)" }}
            >
              {resumeCount} resume{resumeCount !== 1 ? "s" : ""} here
            </span>
          )}
        </div>

        {/* File list */}
        <div className="flex-1 overflow-y-auto px-2 py-2">
          {loading ? (
            <div className="text-center py-8 text-sm" style={{ color: "var(--muted)" }}>
              Loading...
            </div>
          ) : error ? (
            <div className="text-center py-8 text-sm" style={{ color: "var(--danger)" }}>
              {error}
            </div>
          ) : (
            <>
              {/* Go up */}
              {parentPath && (
                <button
                  onClick={() => browse(parentPath)}
                  className="w-full text-left px-4 py-2.5 rounded-lg text-sm flex items-center gap-3 hover:opacity-80"
                  style={{ color: "var(--accent)" }}
                >
                  <FolderIcon color="var(--accent)" />
                  <span>.. (go up)</span>
                </button>
              )}

              {items.map((item) => (
                <button
                  key={item.path}
                  onClick={() => handleItemClick(item)}
                  className="w-full text-left px-4 py-2.5 rounded-lg text-sm flex items-center gap-3 transition-colors"
                  onMouseOver={(e) =>
                    (e.currentTarget.style.background = "var(--bg)")
                  }
                  onMouseOut={(e) =>
                    (e.currentTarget.style.background = "transparent")
                  }
                >
                  {item.type === "folder" ? (
                    <FolderIcon color="var(--warning)" />
                  ) : (
                    <FileIcon ext={item.ext || ""} />
                  )}
                  <span className="flex-1 truncate">{item.name}</span>
                  {item.size && (
                    <span className="text-xs" style={{ color: "var(--muted)" }}>
                      {item.size > 1024
                        ? `${(item.size / 1024).toFixed(1)} MB`
                        : `${item.size} KB`}
                    </span>
                  )}
                </button>
              ))}

              {items.length === 0 && (
                <div className="text-center py-8 text-sm" style={{ color: "var(--muted)" }}>
                  This folder is empty
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer with action */}
        <div
          className="px-5 py-4 flex items-center justify-between"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            {folderCount} folders, {fileCount} files
          </span>
          {mode === "directory" && (
            <button
              onClick={() => onSelect(currentPath)}
              className="px-6 py-2 rounded-lg text-sm font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              Select this folder
              {resumeCount > 0 ? ` (${resumeCount} resumes)` : ""}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function FolderIcon({ color }: { color: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill={color} stroke="none">
      <path d="M2 6a2 2 0 012-2h5l2 2h9a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

function FileIcon({ ext }: { ext: string }) {
  const color =
    ext === ".pdf"
      ? "var(--danger)"
      : ext === ".docx"
      ? "var(--accent)"
      : ext === ".txt"
      ? "var(--muted)"
      : "var(--muted)";

  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}