/**
 * CopilotPanel.tsx — Floating chat panel for Ops Copilot.
 *
 * Features:
 *  • Labeled floating action button with pulse animation on first visit
 *  • Slide-up panel with categorized help/guide view
 *  • Conversation view with markdown-ish rendering
 *  • Categorized suggestion chips (from backend)
 *  • Backend indicator (⚡ Built-in / 🧠 Ollama / ☁️ External)
 *  • Inline settings panel (admin only) for switching backends
 *  • Feedback thumbs up / down per answer
 *  • Keyboard shortcut: Ctrl+K to toggle
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { API_BASE } from "../config";
import "./CopilotPanel.css";

// ── Types ──────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "bot";
  text: string;
  intent?: string | null;
  backend?: string;
  confidence?: number | null;
  historyId?: number | null;
  feedback?: "up" | "down" | null;
  // Feature 2: Copilot Can Act
  actionAvailable?: boolean;
  runbookName?: string | null;
  riskLevel?: string | null;
  supportsDryRun?: boolean;
  executionId?: string | null;
  executionStatus?: string | null;
}

interface ChipDef {
  label: string;
  question: string;
  template?: boolean;
}

interface CategoryDef {
  name: string;
  icon: string;
  chips: ChipDef[];
}

interface SuggestionsData {
  categories: CategoryDef[];
  tips: string[];
}

interface CopilotConfig {
  backend: string;
  ollama_url: string;
  ollama_model: string;
  openai_api_key: string;
  openai_model: string;
  anthropic_api_key: string;
  anthropic_model: string;
  redact_sensitive: boolean;
  system_prompt: string;
  ai_triage_enabled: boolean;
  ai_triage_min_severity: string;
  ai_triage_max_per_hour: number;
  ai_triage_notify_email: boolean;
  [key: string]: unknown;
}

interface CopilotPanelProps {
  token: string | null;
  isAdmin?: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const BACKEND_LABELS: Record<string, { icon: string; label: string }> = {
  builtin:   { icon: "⚡", label: "Built-in" },
  ollama:    { icon: "🧠", label: "Ollama" },
  openai:    { icon: "☁️", label: "OpenAI" },
  anthropic: { icon: "☁️", label: "Anthropic" },
};

let msgCounter = 0;
const nextId = () => `m-${++msgCounter}`;

/** Render Markdown to sanitized HTML using marked.js + DOMPurify. */
function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(html);
}

// ── Component ──────────────────────────────────────────────────────────────

const CopilotPanel: React.FC<CopilotPanelProps> = ({ token, isAdmin }) => {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"chat" | "settings" | "help">("chat");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggestionsData, setSuggestionsData] = useState<SuggestionsData | null>(null);
  const [config, setConfig] = useState<CopilotConfig | null>(null);
  const [editConfig, setEditConfig] = useState<Partial<CopilotConfig>>({});
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string; models?: string[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const [hasOpened, setHasOpened] = useState(() => {
    try { return localStorage.getItem("copilot_opened") === "1"; }
    catch { return false; }
  });
  // Feature 2: Copilot Can Act
  const [actionModal, setActionModal] = useState<{
    msgId: string;
    runbookName: string;
    riskLevel: string;
    supportsDryRun: boolean;
    intentKey: string;
  } | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [executing, setExecuting] = useState(false);
  const [agenticEnabled, setAgenticEnabled] = useState(true);
  const [dryRunChecked, setDryRunChecked] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Focus input when panel opens
  useEffect(() => {
    if (open && view === "chat") {
      setTimeout(() => inputRef.current?.focus(), 120);
    }
  }, [open, view]);

  // Mark as opened (stop pulse)
  useEffect(() => {
    if (open && !hasOpened) {
      setHasOpened(true);
      try { localStorage.setItem("copilot_opened", "1"); } catch {}
    }
  }, [open, hasOpened]);

  // Keyboard shortcut: Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setOpen((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Load suggestions on first open
  useEffect(() => {
    if (open && !suggestionsData && token) {
      fetch(`${API_BASE}/api/copilot/suggestions`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => r.json())
        .then((d) => setSuggestionsData(d?.suggestions || d))
        .catch(() => {});
    }
  }, [open, token, suggestionsData]);

  // Load agentic status on open
  useEffect(() => {
    if (open && token) {
      fetch(`${API_BASE}/api/copilot/agentic-status`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => r.json())
        .then((d) => setAgenticEnabled(d?.enabled !== false))
        .catch(() => {});
    }
  }, [open, token]);

  // Load config when settings view opened
  const loadConfig = useCallback(() => {
    if (!token) return;
    fetch(`${API_BASE}/api/copilot/config`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((d) => {
        setConfig(d);
        setEditConfig({});
        setTestResult(null);
      })
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (view === "settings") loadConfig();
  }, [view, loadConfig]);

  // ── Send question ──────────────────────────────────────────────────

  const sendQuestion = useCallback(
    async (question: string) => {
      if (!question.trim() || !token) return;
      if (view !== "chat") setView("chat");
      const userMsg: Message = { id: nextId(), role: "user", text: question };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);

      try {
        const resp = await fetch(`${API_BASE}/api/copilot/ask`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ question }),
        });
        const data = await resp.json();
        const botMsg: Message = {
          id: nextId(),
          role: "bot",
          text: data.answer || "No answer received.",
          intent: data.intent,
          backend: data.backend_used || "builtin",
          confidence: data.confidence,
          historyId: data.history_id,
          feedback: null,
          actionAvailable: data.action_available || false,
          runbookName: data.runbook_name || null,
          riskLevel: data.risk_level || null,
          supportsDryRun: data.supports_dry_run || false,
        };
        setMessages((prev) => [...prev, botMsg]);
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "bot",
            text: "Failed to reach the Copilot backend. Please check connectivity.",
            backend: "builtin",
            feedback: null,
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [token, view]
  );

  // ── Chip click ────────────────────────────────────────────────────

  const handleChipClick = useCallback(
    (chip: ChipDef) => {
      if (chip.template) {
        setInput(chip.question);
        setView("chat");
        setTimeout(() => inputRef.current?.focus(), 80);
      } else {
        sendQuestion(chip.question);
      }
    },
    [sendQuestion]
  );

  // ── Feedback ──────────────────────────────────────────────────────

  const submitFeedback = useCallback(
    async (msgId: string, historyId: number | null | undefined, helpful: boolean) => {
      if (!historyId || !token) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId ? { ...m, feedback: helpful ? "up" : "down" } : m
        )
      );
      try {
        await fetch(`${API_BASE}/api/copilot/feedback`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ history_id: historyId, helpful }),
        });
      } catch {
        // silently fail
      }
    },
    [token]
  );

  // ── Save config ───────────────────────────────────────────────────

  const saveConfig = useCallback(async () => {
    if (!token || Object.keys(editConfig).length === 0) return;
    setSaving(true);
    try {
      await fetch(`${API_BASE}/api/copilot/config`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(editConfig),
      });
      loadConfig();
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }, [token, editConfig, loadConfig]);

  // ── Test connection ───────────────────────────────────────────────

  const testConnection = useCallback(async () => {
    if (!token || !config) return;
    setTestResult(null);
    const backend = (editConfig.backend || config.backend) as string;
    const payload: Record<string, string> = { backend };
    if (backend === "ollama") {
      payload.url = (editConfig.ollama_url || config.ollama_url) as string;
    } else if (backend === "openai") {
      payload.api_key = (editConfig.openai_api_key || config.openai_api_key) as string;
      payload.model = (editConfig.openai_model || config.openai_model) as string;
    } else if (backend === "anthropic") {
      payload.api_key = (editConfig.anthropic_api_key || config.anthropic_api_key) as string;
      payload.model = (editConfig.anthropic_model || config.anthropic_model) as string;
    }
    try {
      const resp = await fetch(`${API_BASE}/api/copilot/test-connection`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      setTestResult(data);
    } catch (e: unknown) {
      setTestResult({ ok: false, error: String(e) });
    }
  }, [token, config, editConfig]);

  // ── Clear conversation ────────────────────────────────────────────

  const clearChat = () => {
    setMessages([]);
  };

  // ── Execute intent via Copilot (Feature 2) ───────────────────────

  const executeIntent = useCallback(async () => {
    if (!actionModal || !token) return;
    if (actionModal.riskLevel === "high" && confirmText !== "confirm") return;
    setExecuting(true);
    try {
      const resp = await fetch(`${API_BASE}/api/copilot/execute-intent`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          intent_key: actionModal.intentKey,
          runbook_name: actionModal.runbookName,
          confirmed: true,
          dry_run: dryRunChecked,
          parameters: {},
        }),
      });
      const data = await resp.json();
      const execId = data.execution_id ? String(data.execution_id) : null;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === actionModal.msgId
            ? { ...m, executionId: execId, executionStatus: data.status || "dispatched" }
            : m
        )
      );
      setActionModal(null);
      setConfirmText("");
    } catch {
      // keep modal open on error
    } finally {
      setExecuting(false);
    }
  }, [actionModal, token, confirmText, dryRunChecked]);

  // ── Derive active backend label ───────────────────────────────────

  const activeBackend = config?.backend || "builtin";
  const badge = BACKEND_LABELS[activeBackend] || BACKEND_LABELS.builtin;

  // Quick-start chips (first non-template from each category, max 8)
  const quickChips: ChipDef[] = [];
  if (suggestionsData?.categories) {
    for (const cat of suggestionsData.categories) {
      for (const chip of cat.chips) {
        if (quickChips.length < 8 && !chip.template) {
          quickChips.push(chip);
          break;
        }
      }
    }
  }

  // ── Render ────────────────────────────────────────────────────────

  return (
    <>
      {/* Feature 2: Action confirmation modal */}
      {actionModal && (
        <div className="copilot-modal-overlay" onClick={() => { setActionModal(null); setConfirmText(""); }}>
          <div className="copilot-modal" onClick={(e) => e.stopPropagation()}>
            <div className="copilot-modal-header">
              <span className={`copilot-risk-badge ${actionModal.riskLevel}`}>{actionModal.riskLevel}</span>
              <strong>Run runbook</strong>
            </div>
            <div className="copilot-modal-body">
              <p>
                Copilot will trigger{" "}
                <strong>{actionModal.runbookName.replace(/_/g, " ")}</strong> on your behalf.
              </p>
              {actionModal.supportsDryRun && (
                <label className="copilot-dryrun-label">
                  <input
                    type="checkbox"
                    checked={dryRunChecked}
                    onChange={(e) => setDryRunChecked(e.target.checked)}
                  />
                  &nbsp;Dry-run mode (preview only, no changes)
                </label>
              )}
              {actionModal.riskLevel === "high" && (
                <div className="copilot-high-risk-warn">
                  ⚠️ This is a high-risk operation. Type <strong>confirm</strong> to proceed.
                  <input
                    type="text"
                    className="copilot-confirm-input"
                    placeholder='Type "confirm"'
                    value={confirmText}
                    onChange={(e) => setConfirmText(e.target.value)}
                    autoFocus
                  />
                </div>
              )}
            </div>
            <div className="copilot-modal-actions">
              <button
                className="copilot-btn"
                onClick={executeIntent}
                disabled={
                  executing ||
                  (actionModal.riskLevel === "high" && confirmText !== "confirm")
                }
              >
                {executing ? "Running…" : dryRunChecked ? "Preview" : "Execute"}
              </button>
              <button
                className="copilot-btn secondary"
                onClick={() => { setActionModal(null); setConfirmText(""); }}
                disabled={executing}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Floating Action Button — labeled pill, with pulse animation */}
      <button
        className={`copilot-fab ${open ? "open" : ""} ${!hasOpened ? "pulse" : ""}`}
        onClick={() => setOpen((p) => !p)}
        title="Ops Copilot — Ask about your infrastructure (Ctrl+K)"
        aria-label="Toggle Ops Copilot"
      >
        {open ? (
          "✕"
        ) : (
          <>
            <span className="copilot-fab-icon">🤖</span>
            <span className="copilot-fab-label">Ask Copilot</span>
          </>
        )}
      </button>

      {/* Panel */}
      {open && (
        <div className="copilot-panel">
          {/* Header */}
          <div className="copilot-header">
            <div className="copilot-header-left">
              <span className="copilot-icon">🤖</span>
              <span>Ops Copilot</span>
            </div>
            <div className="copilot-header-actions">
              <button
                onClick={() => setView(view === "help" ? "chat" : "help")}
                title="How to Ask — Help & Examples"
                className={view === "help" ? "active" : ""}
              >
                ❓
              </button>
              {isAdmin && (
                <button
                  onClick={() => setView(view === "settings" ? "chat" : "settings")}
                  title="Settings"
                  className={view === "settings" ? "active" : ""}
                >
                  ⚙️
                </button>
              )}
              <button onClick={clearChat} title="Clear conversation">
                🗑️
              </button>
            </div>
          </div>

          {view === "help" ? (
            /* ── Help / Guide view ─────────────────────────────── */
            <div className="copilot-help">
              <div className="copilot-help-intro">
                <strong>Ask about your infrastructure in natural language.</strong>
                <p>Click any chip to run it, or type your own question below.</p>
              </div>

              {/* Categorized chips */}
              {suggestionsData?.categories?.map((cat) => (
                <div key={cat.name} className="copilot-help-category">
                  <div className="copilot-help-cat-name">
                    {cat.icon} {cat.name}
                  </div>
                  <div className="copilot-help-chips">
                    {cat.chips.map((chip, i) => (
                      <button
                        key={i}
                        className={`copilot-chip ${chip.template ? "template" : ""}`}
                        onClick={() => handleChipClick(chip)}
                        title={chip.template ? "Click to fill — complete with a name" : "Click to run"}
                      >
                        {chip.label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}

              {/* Tips */}
              {suggestionsData?.tips && (
                <div className="copilot-help-tips">
                  <div className="copilot-help-tips-title">💡 Tips</div>
                  <ul>
                    {suggestionsData.tips.map((tip, i) => (
                      <li key={i}>{tip}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="copilot-help-footer">
                Backend: {badge.icon} {badge.label}
                {activeBackend === "builtin" && (
                  <span> — pattern-matching mode (no LLM needed)</span>
                )}
              </div>
            </div>
          ) : view === "chat" ? (
            <>
              {/* Quick suggestion chips (shown when no messages) */}
              {messages.length === 0 && quickChips.length > 0 && (
                <div className="copilot-suggestions">
                  {quickChips.map((s, i) => (
                    <button
                      key={i}
                      className="copilot-chip"
                      onClick={() => handleChipClick(s)}
                    >
                      {s.label}
                    </button>
                  ))}
                  <button
                    className="copilot-chip more"
                    onClick={() => setView("help")}
                  >
                    ❓ All questions…
                  </button>
                </div>
              )}

              {/* Messages */}
              <div className="copilot-messages">
                {messages.length === 0 && (
                  <div className="copilot-welcome">
                    <div className="copilot-welcome-icon">🤖</div>
                    <div className="copilot-welcome-title">Hi! I'm Ops Copilot</div>
                    <div className="copilot-welcome-text">
                      Ask me about your infrastructure — VMs, hosts, capacity, tenants, and more.
                    </div>
                    <div className="copilot-welcome-examples">
                      <strong>Try asking:</strong>
                      <ul>
                        <li>"How many powered on VMs on tenant &lt;name&gt;?"</li>
                        <li>"CPU capacity" or "Memory usage"</li>
                        <li>"VMs in error" or "Down hosts"</li>
                        <li>"Infrastructure overview"</li>
                      </ul>
                    </div>
                    <button
                      className="copilot-welcome-help-btn"
                      onClick={() => setView("help")}
                    >
                      ❓ See all available questions &amp; tips
                    </button>
                  </div>
                )}
                {messages.map((m) => (
                  <div key={m.id} className={`copilot-msg ${m.role}`}>
                    {m.role === "bot" ? (
                      <>
                        <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(renderMarkdown(m.text)) }} />
                        {/* Feature 2: Copilot Can Act — action offer */}
                        {m.actionAvailable && m.runbookName && agenticEnabled && (
                          <div className="copilot-action-offer">
                            <span className={`copilot-risk-badge ${m.riskLevel || "low"}`}>
                              {m.riskLevel || "low"}
                            </span>
                            <span>
                              I can run{" "}
                              <strong>{m.runbookName.replace(/_/g, " ")}</strong>{" "}
                              for you
                            </span>
                            <button
                              className="copilot-btn-run"
                              onClick={() => {
                                setDryRunChecked(m.supportsDryRun ?? true);
                                setConfirmText("");
                                setActionModal({
                                  msgId: m.id,
                                  runbookName: m.runbookName!,
                                  riskLevel: m.riskLevel || "low",
                                  supportsDryRun: m.supportsDryRun || false,
                                  intentKey: m.intent || "",
                                });
                              }}
                            >
                              ▶ Run it
                            </button>
                          </div>
                        )}
                        {m.executionId && (
                          <div className="copilot-exec-status">
                            Execution{" "}
                            <code>{m.executionId.slice(0, 8)}…</code>
                            <span className={`rb-status-badge ${m.executionStatus || "dispatched"}`}>
                              {m.executionStatus || "dispatched"}
                            </span>
                          </div>
                        )}
                        <div className="copilot-msg-meta">
                          <span className={`copilot-backend-badge ${m.backend || "builtin"}`}>
                            {BACKEND_LABELS[m.backend || "builtin"]?.icon}{" "}
                            {BACKEND_LABELS[m.backend || "builtin"]?.label}
                          </span>
                          {m.confidence != null && (
                            <span>conf: {Math.round(m.confidence * 100)}%</span>
                          )}
                          {m.historyId && (
                            <span className="copilot-feedback-btns">
                              <button
                                className={m.feedback === "up" ? "active-up" : ""}
                                onClick={() => submitFeedback(m.id, m.historyId, true)}
                                title="Helpful"
                              >
                                👍
                              </button>
                              <button
                                className={m.feedback === "down" ? "active-down" : ""}
                                onClick={() => submitFeedback(m.id, m.historyId, false)}
                                title="Not helpful"
                              >
                                👎
                              </button>
                            </span>
                          )}
                        </div>
                      </>
                    ) : (
                      m.text
                    )}
                  </div>
                ))}
                {loading && (
                  <div className="copilot-typing">
                    <span /><span /><span />
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

            </>
          ) : (
            /* ── Settings view ─────────────────────────────────── */
            <div className="copilot-settings">
              <h4>Copilot Settings</h4>

              <label>Backend</label>
              <select
                value={(editConfig.backend ?? config?.backend) || "builtin"}
                onChange={(e) => setEditConfig((p) => ({ ...p, backend: e.target.value }))}
              >
                <option value="builtin">⚡ Built-in (no LLM, zero setup)</option>
                <option value="ollama">🧠 Ollama (local LLM)</option>
                <option value="openai">☁️ OpenAI</option>
                <option value="anthropic">☁️ Anthropic</option>
              </select>

              {((editConfig.backend ?? config?.backend) === "ollama") && (
                <>
                  <label>Ollama URL</label>
                  <input
                    type="text"
                    value={(editConfig.ollama_url ?? config?.ollama_url) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, ollama_url: e.target.value }))}
                    placeholder="http://localhost:11434"
                  />
                  <label>Ollama Model</label>
                  <input
                    type="text"
                    value={(editConfig.ollama_model ?? config?.ollama_model) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, ollama_model: e.target.value }))}
                    placeholder="llama3"
                  />
                </>
              )}

              {((editConfig.backend ?? config?.backend) === "openai") && (
                <>
                  <label>OpenAI API Key</label>
                  <input
                    type="password"
                    value={(editConfig.openai_api_key ?? config?.openai_api_key) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, openai_api_key: e.target.value }))}
                    placeholder="sk-..."
                  />
                  <label>OpenAI Model</label>
                  <input
                    type="text"
                    value={(editConfig.openai_model ?? config?.openai_model) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, openai_model: e.target.value }))}
                    placeholder="gpt-4o-mini"
                  />
                </>
              )}

              {((editConfig.backend ?? config?.backend) === "anthropic") && (
                <>
                  <label>Anthropic API Key</label>
                  <input
                    type="password"
                    value={(editConfig.anthropic_api_key ?? config?.anthropic_api_key) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, anthropic_api_key: e.target.value }))}
                    placeholder="sk-ant-..."
                  />
                  <label>Anthropic Model</label>
                  <input
                    type="text"
                    value={(editConfig.anthropic_model ?? config?.anthropic_model) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, anthropic_model: e.target.value }))}
                    placeholder="claude-sonnet-4-20250514"
                  />
                </>
              )}

              {((editConfig.backend ?? config?.backend) === "openai" ||
                (editConfig.backend ?? config?.backend) === "anthropic") && (
                <div className="copilot-settings-row" style={{ marginTop: 12 }}>
                  <input
                    type="checkbox"
                    id="copilot-redact"
                    checked={(editConfig.redact_sensitive ?? config?.redact_sensitive) || false}
                    onChange={(e) =>
                      setEditConfig((p) => ({ ...p, redact_sensitive: e.target.checked }))
                    }
                  />
                  <label htmlFor="copilot-redact" style={{ margin: 0 }}>
                    Redact sensitive data before sending to external LLM
                  </label>
                </div>
              )}

              {((editConfig.backend ?? config?.backend) !== "builtin") && (
                <>
                  <label>System Prompt</label>
                  <textarea
                    value={(editConfig.system_prompt ?? config?.system_prompt) || ""}
                    onChange={(e) => setEditConfig((p) => ({ ...p, system_prompt: e.target.value }))}
                    rows={3}
                  />
                </>
              )}

              <hr style={{ margin: "14px 0", border: "none", borderTop: "1px solid var(--color-border)" }} />
              <h4 style={{ margin: "0 0 10px 0" }}>AI Incident Triage</h4>

              <div className="copilot-settings-row" style={{ marginTop: 8 }}>
                <input
                  type="checkbox"
                  id="copilot-ai-triage-enabled"
                  checked={(editConfig.ai_triage_enabled ?? config?.ai_triage_enabled) || false}
                  onChange={(e) =>
                    setEditConfig((p) => ({ ...p, ai_triage_enabled: e.target.checked }))
                  }
                />
                <label htmlFor="copilot-ai-triage-enabled" style={{ margin: 0 }}>
                  Enable proactive AI incident triage briefs
                </label>
              </div>

              <label style={{ marginTop: 10 }}>Minimum Severity</label>
              <select
                value={(editConfig.ai_triage_min_severity ?? config?.ai_triage_min_severity ?? "critical") as string}
                onChange={(e) => setEditConfig((p) => ({ ...p, ai_triage_min_severity: e.target.value }))}
              >
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>

              <label>Max Briefs Per Hour</label>
              <input
                type="number"
                min={1}
                max={200}
                value={Number(editConfig.ai_triage_max_per_hour ?? config?.ai_triage_max_per_hour ?? 10)}
                onChange={(e) =>
                  setEditConfig((p) => ({
                    ...p,
                    ai_triage_max_per_hour: Math.max(1, Math.min(200, Number(e.target.value || 10))),
                  }))
                }
              />

              <div className="copilot-settings-row" style={{ marginTop: 8 }}>
                <input
                  type="checkbox"
                  id="copilot-ai-triage-email"
                  checked={(editConfig.ai_triage_notify_email ?? config?.ai_triage_notify_email) || false}
                  onChange={(e) =>
                    setEditConfig((p) => ({ ...p, ai_triage_notify_email: e.target.checked }))
                  }
                />
                <label htmlFor="copilot-ai-triage-email" style={{ margin: 0 }}>
                  Send email notifications for generated briefs
                </label>
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <button className="copilot-btn" onClick={saveConfig} disabled={saving}>
                  {saving ? "Saving…" : "Save"}
                </button>
                {(editConfig.backend ?? config?.backend) !== "builtin" && (
                  <button className="copilot-btn secondary" onClick={testConnection}>
                    Test Connection
                  </button>
                )}
              </div>

              {testResult && (
                <div className={`copilot-test-result ${testResult.ok ? "ok" : "fail"}`}>
                  {testResult.ok
                    ? `✅ Connected${testResult.models ? ` — Models: ${testResult.models.join(", ")}` : ""}`
                    : `❌ Failed: ${testResult.error}`}
                </div>
              )}
            </div>
          )}

          {/* ── Input area (visible in chat + help views) ─────── */}
          {view !== "settings" && (
            <>
              <div className="copilot-input-area">
                <input
                  ref={inputRef}
                  type="text"
                  placeholder="Ask about your infrastructure..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (view !== "chat") setView("chat");
                      sendQuestion(input);
                    }
                  }}
                  disabled={loading}
                />
                <button
                  className="copilot-send"
                  onClick={() => {
                    if (view !== "chat") setView("chat");
                    sendQuestion(input);
                  }}
                  disabled={loading || !input.trim()}
                  title="Send"
                >
                  ➤
                </button>
              </div>

              <div className="copilot-footer">
                {view === "help" ? (
                  <span className="copilot-footer-help" onClick={() => setView("chat")}>
                    ← Back to chat
                  </span>
                ) : (
                  <span className="copilot-footer-help" onClick={() => setView("help")}>
                    ❓ How to ask
                  </span>
                )}
                <span>Ctrl+K</span>
                <span className={`copilot-backend-badge ${activeBackend}`}>
                  {badge.icon} {badge.label}
                </span>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
};

export default CopilotPanel;

/* ── Helper: Action Confirmation Modal ────────────────────────────────────
   Rendered outside the panel so it overlays the full viewport.           */
// NOTE: The modal is rendered inline inside CopilotPanel's return()
// (see JSX at the bottom of the component above). The placeholder below
// is a type-only reference kept here for documentation.
// -------------------------------------------------------------------------
