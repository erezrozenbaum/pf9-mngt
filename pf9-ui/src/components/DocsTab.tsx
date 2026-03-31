import React, { useState, useEffect, useCallback, useRef } from "react";
import { marked } from "marked";
import { API_BASE } from "../config";
import "../styles/DocsTab.css";

/* =========================================================================
   DocsTab — In-app documentation viewer with department visibility control
   =========================================================================
   Tabs:
     1. Browse Docs  – left sidebar file list + right panel markdown viewer
     2. Visibility   – (admin only) per-file department access control
*/

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DocEntry {
  filename: string;
  category: string;
  title: string;
}

interface DocVisibilityItem {
  filename: string;
  dept_ids: number[];
}

interface Department {
  id: number;
  name: string;
}

interface DocsTabProps {
  userRole: string;
  isAdmin: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const isJson = opts?.body && !(opts.body instanceof FormData);
  const headers: Record<string, string> = {
    ...(isJson ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function groupByCategory(entries: DocEntry[]): Map<string, DocEntry[]> {
  const map = new Map<string, DocEntry[]>();
  for (const e of entries) {
    if (!map.has(e.category)) map.set(e.category, []);
    map.get(e.category)!.push(e);
  }
  return map;
}

// Render markdown safely using marked
function renderMarkdown(md: string): string {
  // marked.parse returns string (sync) when given a string
  return marked.parse(md) as string;
}

// ---------------------------------------------------------------------------
// Visibility Edit Modal
// ---------------------------------------------------------------------------

interface VisibilityEditModalProps {
  item: DocVisibilityItem;
  departments: Department[];
  onSave: (filename: string, deptIds: number[]) => Promise<void>;
  onClose: () => void;
}

function VisibilityEditModal({ item, departments, onSave, onClose }: VisibilityEditModalProps) {
  const [selected, setSelected] = useState<Set<number>>(new Set(item.dept_ids));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(id: number) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await onSave(item.filename, [...selected]);
      onClose();
    } catch (err: any) {
      setError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="docs-modal-overlay" onClick={onClose}>
      <div className="docs-modal" onClick={e => e.stopPropagation()}>
        <h3>Set Visibility — {item.filename}</h3>
        <p className="docs-modal-help">
          Select departments that can view this file.
          Leave all unselected to make it visible to <strong>everyone</strong>.
        </p>

        {error && <div className="docs-error">{error}</div>}

        <div className="docs-modal-depts">
          {departments.map(dept => (
            <button
              key={dept.id}
              className={`docs-modal-dept-btn${selected.has(dept.id) ? " selected" : ""}`}
              onClick={() => toggle(dept.id)}
            >
              {dept.name}
            </button>
          ))}
        </div>

        <div className="docs-modal-actions">
          <button className="docs-btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="docs-btn primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function DocsTab({ userRole, isAdmin }: DocsTabProps) {
  const [subTab, setSubTab] = useState<"browse" | "visibility">("browse");

  // ── Browse state ────────────────────────────────────────────────────────
  const [docs, setDocs] = useState<DocEntry[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [search, setSearch] = useState("");

  // ── Visibility admin state ───────────────────────────────────────────────
  const [visibility, setVisibility] = useState<DocVisibilityItem[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [visLoading, setVisLoading] = useState(false);
  const [visError, setVisError] = useState<string | null>(null);
  const [editingItem, setEditingItem] = useState<DocVisibilityItem | null>(null);

  const contentRef = useRef<HTMLDivElement>(null);

  // ── Load doc list ────────────────────────────────────────────────────────
  const loadDocs = useCallback(async () => {
    setDocsLoading(true);
    setDocsError(null);
    try {
      const data = await apiFetch<DocEntry[]>("/api/docs/");
      setDocs(data);
    } catch (err: any) {
      setDocsError(err.message || "Failed to load docs");
    } finally {
      setDocsLoading(false);
    }
  }, []);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  // ── Load file content ────────────────────────────────────────────────────
  const openFile = useCallback(async (filename: string) => {
    setSelectedFile(filename);
    setContent(null);
    setContentLoading(true);
    try {
      const data = await apiFetch<{ filename: string; content: string }>(
        `/api/docs/content/${encodeURIComponent(filename)}`
      );
      setContent(data.content);
    } catch (err: any) {
      setContent(`> **Error loading file:** ${err.message}`);
    } finally {
      setContentLoading(false);
    }
    contentRef.current?.scrollTo({ top: 0 });
  }, []);

  // ── Load visibility settings (admin only) ────────────────────────────────
  const loadVisibility = useCallback(async () => {
    setVisLoading(true);
    setVisError(null);
    try {
      const [vis, deptData] = await Promise.all([
        apiFetch<DocVisibilityItem[]>("/api/docs/admin/visibility"),
        apiFetch<{ departments: Department[] }>("/api/departments"),
      ]);
      setVisibility(vis);
      setDepartments(deptData.departments);
    } catch (err: any) {
      setVisError(err.message || "Failed to load visibility settings");
    } finally {
      setVisLoading(false);
    }
  }, []);

  useEffect(() => {
    if (subTab === "visibility" && isAdmin) {
      loadVisibility();
    }
  }, [subTab, isAdmin, loadVisibility]);

  // ── Save visibility ──────────────────────────────────────────────────────
  async function saveVisibility(filename: string, deptIds: number[]) {
    await apiFetch("/api/docs/admin/visibility", {
      method: "PUT",
      body: JSON.stringify({ filename, dept_ids: deptIds }),
    });
    // Optimistically update local state
    setVisibility(prev =>
      prev.map(item => item.filename === filename ? { ...item, dept_ids: deptIds } : item)
    );
  }

  // ── Filtered doc list ────────────────────────────────────────────────────
  const filteredDocs = search.trim()
    ? docs.filter(d =>
        d.title.toLowerCase().includes(search.toLowerCase()) ||
        d.filename.toLowerCase().includes(search.toLowerCase()) ||
        d.category.toLowerCase().includes(search.toLowerCase())
      )
    : docs;

  const grouped = groupByCategory(filteredDocs);
  const sortedCategories = [...grouped.keys()].sort();

  // ── Dept name lookup ─────────────────────────────────────────────────────
  const deptName = (id: number) =>
    departments.find(d => d.id === id)?.name ?? String(id);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="docs-container">
      <div className="docs-header">
        <h2>📚 Documentation</h2>
        <p className="docs-subtitle">
          Browse operational guides, runbooks, and reference docs.
          {isAdmin && " Visibility controls available in the Admin tab."}
        </p>
      </div>

      {/* Sub-tabs */}
      <div className="docs-subtabs">
        <button
          className={`docs-subtab${subTab === "browse" ? " active" : ""}`}
          onClick={() => setSubTab("browse")}
        >
          Browse
        </button>
        {isAdmin && (
          <button
            className={`docs-subtab${subTab === "visibility" ? " active" : ""}`}
            onClick={() => setSubTab("visibility")}
          >
            Visibility Admin
          </button>
        )}
      </div>

      {/* ── Browse tab ──────────────────────────────────────────────────── */}
      {subTab === "browse" && (
        <div className="docs-layout">
          {/* Sidebar */}
          <div className="docs-sidebar">
            <div className="docs-search-wrap">
              <input
                className="docs-search"
                type="search"
                placeholder="Search docs…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>

            {docsLoading && <div className="docs-loading">Loading…</div>}
            {docsError && <div className="docs-error">{docsError}</div>}

            {!docsLoading && !docsError && filteredDocs.length === 0 && (
              <div className="docs-loading" style={{ textAlign: "left", padding: "8px 4px" }}>
                No matching docs found.
              </div>
            )}

            {sortedCategories.map(cat => (
              <div key={cat} className="docs-category">
                <span className="docs-category-label">{cat}</span>
                {grouped.get(cat)!.map(doc => (
                  <button
                    key={doc.filename}
                    className={`docs-file-btn${selectedFile === doc.filename ? " active" : ""}`}
                    onClick={() => openFile(doc.filename)}
                    title={doc.filename}
                  >
                    {doc.title}
                  </button>
                ))}
              </div>
            ))}
          </div>

          {/* Content panel */}
          <div className="docs-content-panel" ref={contentRef}>
            {!selectedFile && (
              <div className="docs-placeholder">
                <span className="docs-placeholder-icon">📖</span>
                Select a document from the left panel to read it here.
              </div>
            )}

            {selectedFile && (
              <>
                <div className="docs-content-toolbar">
                  <span className="docs-content-title">{selectedFile}</span>
                  <button
                    className="docs-btn"
                    onClick={() => {
                      if (content) {
                        const blob = new Blob([content], { type: "text/markdown" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = selectedFile;
                        a.click();
                        URL.revokeObjectURL(url);
                      }
                    }}
                    disabled={!content}
                  >
                    ⬇ Download
                  </button>
                </div>

                {contentLoading && <div className="docs-loading">Loading content…</div>}

                {!contentLoading && content !== null && (
                  <div
                    className="docs-markdown"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
                  />
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Visibility Admin tab ─────────────────────────────────────────── */}
      {subTab === "visibility" && isAdmin && (
        <div>
          {visLoading && <div className="docs-loading">Loading visibility settings…</div>}
          {visError && <div className="docs-error">{visError}</div>}

          {!visLoading && !visError && (
            <>
              <p style={{ fontSize: 13, color: "var(--color-text-secondary, #666)", marginBottom: 14 }}>
                Files with <strong>no department restrictions</strong> (shown as "All depts") are visible to every user.
                Click <em>Edit</em> to restrict a file to specific departments.
              </p>
              <table className="docs-vis-table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Category</th>
                    <th>Visible to</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visibility.map(item => {
                    const docMeta = docs.find(d => d.filename === item.filename);
                    return (
                      <tr key={item.filename}>
                        <td>{item.filename}</td>
                        <td>{docMeta?.category ?? "—"}</td>
                        <td>
                          {item.dept_ids.length === 0 ? (
                            <span className="docs-vis-tag all">All depts</span>
                          ) : (
                            item.dept_ids.map(id => (
                              <span key={id} className="docs-vis-tag">{deptName(id)}</span>
                            ))
                          )}
                        </td>
                        <td>
                          <button
                            className="docs-vis-edit-btn"
                            onClick={() => setEditingItem(item)}
                          >
                            Edit
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      {/* Visibility edit modal */}
      {editingItem && (
        <VisibilityEditModal
          item={editingItem}
          departments={departments}
          onSave={saveVisibility}
          onClose={() => setEditingItem(null)}
        />
      )}
    </div>
  );
}
