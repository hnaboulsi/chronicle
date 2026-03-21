import React, { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";

// ── Types ──────────────────────────────────────────────────────────────────────

type DashboardState = {
  backend_target_url?: string;
  mac_status?: string;
  mac_status_reason?: string;
  mac_idle?: boolean;
  last_mac_heartbeat_age_seconds?: number;
  last_mac_capture_age_seconds?: number;
  current_activity_category?: string;
  current_activity_summary?: string;
  current_location?: string;
  ios_recent_event?: boolean;
  ios_ever_setup?: boolean;
  sleep_status_note?: string;
  service_health?: string;
  tracking_enabled?: string;
  capture_interval_seconds?: number;
  presence_state?: string;
  presence_display?: string;
  presence_display_label?: string | null;
  current_event_title?: string | null;
  next_event_title?: string | null;
  next_event_starts_in_minutes?: number | null;
  last_presence_change_at?: string;
  screen_state?: string;
  privacy_mode?: string;
  calendar_sync_enabled?: boolean;
  last_heartbeat_at?: string;
  last_capture_at?: string;
  at_location_mac_note?: string | null;
};

type BackendSettings = {
  capture_interval_seconds: number;
  polling_interval_seconds: number;
  tracking_enabled: boolean;
  backend_mode: string;
  ai_provider: string;
  ai_primary_provider?: string;
  ai_fallback_providers: string[];
  ai_routing_mode: string;
  llm_mode: string;
  hourly_summaries_enabled: boolean;
  classification_interval_seconds: number;
  llm_daily_cap?: number | null;
  user_timezone: string;
  privacy_mode: "private" | "detailed";
  calendar_sync_enabled: boolean;
  calendar_ical_url: string;
  calendar_ical_urls: string[];
  calendar_last_sync: string;
  calendar_sync_error: string;
};

type Analytics = {
  total_active_minutes: number;
  productive_minutes: number;
  productive_pct: number;
  steps_today: number;
  llm_used: number;
  llm_cap: number;
  log_count: number;
  category_minutes?: Record<string, number>;
};

type ActivityLog = {
  id: number;
  timestamp: string;
  device: string;
  app_name?: string;
  window_title?: string;
  is_idle?: boolean;
  location_label?: string;
  activity_type?: string;
  steps_today?: number;
  battery_pct?: number;
  presence_state?: string;
  screen_state?: string;
};

type HealthResponse = {
  status: string;
  uptime_seconds?: number;
  startup_errors?: string[];
  llm?: {
    configured?: boolean;
    provider?: string | null;
  };
};

type HourlySummary = {
  id: number;
  hour_start_local: string;
  summary_text: string;
  productivity_score: number | null;
};

type ZoneRecord = {
  id?: number;
  slug: string;
  name: string;
  radius_meters: number;
  enabled: boolean;
  zone_type: string;
  focus_mode: string;
  sort_order: number;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ?? "";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return (await response.json()) as T;
}

function serviceTone(value?: string) {
  if (value === "ok" || value === "online") return "good";
  if (value === "offline") return "bad";
  return "warn";
}

function timeGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning.";
  if (hour < 18) return "Good afternoon.";
  return "Good evening.";
}

function productivityGrade(pct: number): string {
  if (pct >= 90) return "A+";
  if (pct >= 80) return "A";
  if (pct >= 70) return "B";
  if (pct >= 60) return "C";
  if (pct >= 50) return "D";
  return "F";
}

function gradeColor(grade: string): string {
  if (grade === "A+" || grade === "A") return "var(--good)";
  if (grade === "B") return "var(--accent)";
  if (grade === "C") return "var(--warn)";
  return "var(--bad)";
}

function getRecentApps(logs: ActivityLog[]): string[] {
  const counts: Record<string, number> = {};
  for (const log of logs) {
    if (log.app_name) counts[log.app_name] = (counts[log.app_name] ?? 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const apps = sorted.slice(0, 3).map(([name]) => name.toUpperCase());
  const fallbacks = ["VS CODE", "TERMINAL", "DOCS"];
  while (apps.length < 3) apps.push(fallbacks[apps.length]);
  return apps;
}

function productivePulseData(
  hourlySummaries: HourlySummary[],
  productivePct?: number
) {
  const values = hourlySummaries
    .slice(0, 10)
    .reverse()
    .map((s) =>
      Math.max(12, Math.min(100, Math.round((s.productivity_score ?? 4.5) * 10)))
    );
  if (values.length >= 6) return values;
  const seed = Math.max(20, Math.min(96, productivePct ?? 64));
  return Array.from({ length: 14 }, (_, i) =>
    Math.max(18, Math.min(100, Math.round(seed + ((i % 4) - 2) * 8)))
  );
}

function formatTimestamp(ts: string): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatHour(ts: string): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "numeric",
    hour12: true,
  });
}

// ── NavItem ────────────────────────────────────────────────────────────────────

function NavItem({ to, label, dim }: { to: string; label: string; dim?: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `nav-item${dim ? " nav-dim" : ""}${isActive ? " active" : ""}`
      }
    >
      {label}
    </NavLink>
  );
}

// ── Log Panel ─────────────────────────────────────────────────────────────────

function LogPanel({
  logs,
  open,
  onClose,
}: {
  logs: ActivityLog[];
  open: boolean;
  onClose: () => void;
}) {
  return (
    <>
      {open && <div className="log-panel-backdrop" onClick={onClose} />}
      <aside className={`log-panel${open ? " log-panel-open" : ""}`}>
        <div className="log-panel-header">
          <span className="section-eyebrow" style={{ margin: 0 }}>
            OPERATIONAL LOG
          </span>
          <button className="log-panel-close" onClick={onClose} type="button">
            ✕
          </button>
        </div>
        <div className="log-panel-body">
          {logs.length === 0 ? (
            <p className="log-panel-empty">
              No logs yet. Start tracking to see activity.
            </p>
          ) : (
            logs.map((log) => (
              <div key={log.id} className={`log-entry log-entry-${log.device}`}>
                <div className="log-entry-header">
                  <span className="log-entry-device">
                    {log.device.toUpperCase()}
                  </span>
                  <span className="log-entry-time">
                    {formatTimestamp(log.timestamp)}
                  </span>
                </div>
                {log.app_name && (
                  <div className="log-entry-app">{log.app_name}</div>
                )}
                {log.window_title && (
                  <div className="log-entry-window">{log.window_title}</div>
                )}
                {log.location_label && (
                  <div className="log-entry-location">
                    📍 {log.location_label}
                  </div>
                )}
                {log.presence_state && (
                  <div className="log-entry-meta">
                    {log.presence_state.toUpperCase()}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </aside>
    </>
  );
}

// ── AppShell ──────────────────────────────────────────────────────────────────

function AppShell({
  children,
  statusMessage,
  errorMessage,
  refreshing,
  onRefresh,
  state,
  logs,
}: {
  children: ReactNode;
  statusMessage: string;
  errorMessage: string;
  refreshing: boolean;
  onRefresh: () => void;
  state: DashboardState | null;
  logs: ActivityLog[];
}) {
  const [logPanelOpen, setLogPanelOpen] = useState(false);
  const navigate = useNavigate();

  const liveCategory = state?.mac_idle
    ? "IDLE"
    : (state?.current_activity_category?.toUpperCase() ?? null);

  function handleLogIntent() {
    navigate("/today");
    setTimeout(() => {
      const input = document.getElementById("intent-input") as HTMLInputElement | null;
      if (input) {
        input.scrollIntoView({ behavior: "smooth" });
        input.focus();
      }
    }, 80);
  }

  return (
    <div className="app-shell">
      <aside className="side-rail">
        <Link to="/today" className="brand-mark">
          <span className="brand-title">CHRONICLE</span>
        </Link>
        <nav className="side-rail-nav">
          <NavItem to="/today" label="Today" />
          <NavItem to="/diagnostics" label="History" />
        </nav>
        <div className="sidebar-footer">
          <NavItem to="/settings" label="Settings" dim />
          <button
            className="log-intent-btn"
            type="button"
            onClick={handleLogIntent}
          >
            LOG INTENT
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <span className="brand-title">CHRONICLE</span>
            <button
              className="topbar-status-tag topbar-log-btn"
              type="button"
              onClick={() => setLogPanelOpen((v) => !v)}
            >
              OPERATIONAL LOG
            </button>
            {liveCategory && (
              <span className="topbar-live-indicator">
                <span className="live-dot" />
                {liveCategory}
              </span>
            )}
          </div>

          <div className="topbar-actions">
            <button
              className="refresh-btn"
              onClick={onRefresh}
              type="button"
              disabled={refreshing}
            >
              {refreshing ? "SYNCHRONIZING..." : "REFRESH"}
            </button>
            <div
              style={{
                width: 36,
                height: 36,
                background: "var(--panel-bright)",
                borderRadius: 2,
              }}
            />
          </div>
        </header>

        <main className="content">
          {statusMessage && (
            <div className="banner success">{statusMessage}</div>
          )}
          {errorMessage && <div className="banner error">{errorMessage}</div>}
          {children}
        </main>

        <footer className="app-footer">
          <div className="app-footer-left">
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <span
                className={`sidebar-status-dot bg-${serviceTone(state?.service_health)}`}
              />
              <span>
                {state?.service_health === "ok"
                  ? "SYSTEM UPLINK ACTIVE"
                  : "SYSTEM OFFLINE"}
              </span>
            </div>
            <span>CHRONICLE OBSERVATORY</span>
          </div>
          <div className="app-footer-right">
            <span>
              {state?.current_location?.toUpperCase() ?? "AWAITING PLACE CONTEXT"}
            </span>
          </div>
        </footer>

        <LogPanel
          logs={logs}
          open={logPanelOpen}
          onClose={() => setLogPanelOpen(false)}
        />
      </div>
    </div>
  );
}

// ── TodayPage ─────────────────────────────────────────────────────────────────

function TodayPage({
  state,
  analytics,
  logs,
  hourlySummaries,
  aiDayInsight,
  onRefreshLogs,
}: {
  state: DashboardState | null;
  analytics: Analytics | null;
  logs: ActivityLog[];
  hourlySummaries: HourlySummary[];
  aiDayInsight?: string | null;
  onRefreshLogs: () => void;
}) {
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);

  useEffect(() => {
    document.title = state?.mac_idle ? "Chronicle (Idle)" : "Chronicle";
  }, [state?.mac_idle]);

  async function handleChat() {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatSending(true);
    setChatInput("");
    try {
      await fetchJson("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: msg }),
      });
      onRefreshLogs();
    } finally {
      setChatSending(false);
    }
  }

  const pulseValues = productivePulseData(hourlySummaries, analytics?.productive_pct);
  const recentApps = getRecentApps(logs);
  const grade = productivityGrade(analytics?.productive_pct ?? 0);
  const gColor = gradeColor(grade);

  const sortedSummaries = [...hourlySummaries].sort(
    (a, b) =>
      new Date(a.hour_start_local).getTime() -
      new Date(b.hour_start_local).getTime()
  );
  const pulseStart =
    sortedSummaries.length > 0
      ? formatHour(sortedSummaries[0].hour_start_local)
      : "START";
  const pulseEnd =
    sortedSummaries.length > 0
      ? formatHour(sortedSummaries[sortedSummaries.length - 1].hour_start_local)
      : "NOW";

  const envStatus = state?.mac_idle
    ? "IDLE"
    : (state?.current_activity_category?.toUpperCase() ??
        state?.current_location?.toUpperCase() ??
        "STABLE");

  const adminMinutes = Math.max(
    0,
    (analytics?.total_active_minutes ?? 0) - (analytics?.productive_minutes ?? 0)
  );

  const categoryMinutes = analytics?.category_minutes ?? {};
  const categoryEntries = Object.entries(categoryMinutes)
    .filter(([, mins]) => mins > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);
  const totalMins = Math.max(analytics?.total_active_minutes ?? 0, 1);
  const productiveCategories = new Set(["studying", "working", "creative"]);

  return (
    <div className="editorial-page">
      <div className="editorial-grid">
        <div className="editorial-left">
          <section className="hero-section">
            <span className="section-eyebrow" style={{ color: "var(--accent)" }}>
              SESSION ACTIVE
            </span>
            <h1 className="main-greeting">{timeGreeting()}</h1>

            <div className="intent-selection">
              <span className="section-eyebrow">INTENT SELECTION</span>
              <input
                id="intent-input"
                className="editorial-intent-input"
                placeholder="Define your trajectory..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !chatSending) void handleChat();
                }}
              />
            </div>

            <div className="recent-channels">
              <span className="section-eyebrow">RECENT CHANNELS</span>
              <div className="channel-btns">
                {recentApps.map((app) => (
                  <button
                    key={app}
                    className="channel-btn"
                    type="button"
                    onClick={() => setChatInput(app)}
                  >
                    {app}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </div>

        <div className="editorial-right">
          <article className="editorial-card session-chronicle">
            <span className="section-eyebrow">SESSION CHRONICLE</span>
            <span className="card-subtitle">INTELLIGENCE SUMMARY</span>
            <p className="summary-text">
              {aiDayInsight || "Collecting signals to form the daily chronicle..."}
            </p>
            <div className="card-meta">
              <div className="meta-item">
                <svg
                  className="meta-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                <span>
                  ENVIRONMENT: {state?.current_location?.toUpperCase() ?? "STABLE"}
                </span>
              </div>
              <div className="meta-item">
                <svg
                  className="meta-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M12 2v10l4.5 4.5" />
                  <circle cx="12" cy="12" r="10" />
                </svg>
                <span>
                  OUTPUT: {analytics?.log_count ?? 0} LOGS / {analytics?.llm_used ?? 0} LLM
                </span>
              </div>
            </div>
          </article>

          <article className="editorial-card productivity-pulse">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
              }}
            >
              <span className="section-eyebrow">PRODUCTIVITY PULSE</span>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: "0.75rem",
                }}
              >
                <span className="pulse-grade" style={{ color: gColor }}>
                  {grade}
                </span>
                <span className="pulse-pct">{analytics?.productive_pct ?? 0}%</span>
              </div>
            </div>
            <span className="card-subtitle">HIGH-FREQUENCY OUTPUT</span>
            <div className="pulse-bars">
              {pulseValues.map((v, i) => (
                <div
                  key={i}
                  className="pulse-bar-item"
                  style={{ height: `${v}%` }}
                />
              ))}
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "0.55rem",
                color: "var(--muted)",
                fontWeight: 800,
                letterSpacing: "0.1em",
              }}
            >
              <span>{pulseStart}</span>
              <span style={{ color: "var(--accent)" }}>LIVE NOW</span>
              <span>{pulseEnd}</span>
            </div>
            {categoryEntries.length > 0 && (
              <div className="category-breakdown">
                {categoryEntries.map(([cat, mins]) => (
                  <div key={cat} className="category-row">
                    <span className="category-name">{cat.toUpperCase()}</span>
                    <div className="category-bar-track">
                      <div
                        className="category-bar-fill"
                        style={{
                          width: `${(mins / totalMins) * 100}%`,
                          background: productiveCategories.has(cat)
                            ? "var(--accent)"
                            : "var(--panel-bright)",
                        }}
                      />
                    </div>
                    <span className="category-mins">{mins}m</span>
                  </div>
                ))}
              </div>
            )}
          </article>
        </div>
      </div>

      <footer className="editorial-footer">
        <div className="metric-group">
          <div className="metric-item">
            <span className="metric-value">
              {analytics?.productive_minutes ?? 0}m
            </span>
            <span className="metric-label">PRODUCTIVE</span>
          </div>
          <div className="metric-item">
            <span className="metric-value">{adminMinutes}m</span>
            <span className="metric-label">ADMINISTRATIVE</span>
          </div>
          <div className="metric-item">
            <span className="metric-value">{envStatus}</span>
            <span className="metric-label">ENVIRONMENT</span>
          </div>
        </div>
        <div className="ticker">
          REFINING INTELLIGENCE FEED{" "}
          <span style={{ opacity: 0.3 }}>● ● ●</span>
        </div>
      </footer>
    </div>
  );
}

// ── ZonesPage ─────────────────────────────────────────────────────────────────

function ZonesPage() {
  const [zones, setZones] = useState<ZoneRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [newZone, setNewZone] = useState<Partial<ZoneRecord>>({
    slug: "",
    name: "",
    radius_meters: 75,
    enabled: true,
    zone_type: "custom",
    focus_mode: "",
    sort_order: 0,
  });

  useEffect(() => {
    document.title = "Chronicle — Places";
    void load();
  }, []);

  async function load() {
    setLoading(true);
    try {
      const data = await fetchJson<ZoneRecord[]>("/api/zones");
      setZones(data);
      setError("");
    } catch {
      setError("Failed to load places.");
    } finally {
      setLoading(false);
    }
  }

  async function toggleZone(zone: ZoneRecord) {
    if (!zone.id) return;
    try {
      await fetchJson(`/api/zones/${zone.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !zone.enabled }),
      });
      await load();
    } catch {
      setError("Failed to update place.");
    }
  }

  async function deleteZone(zone: ZoneRecord) {
    if (!zone.id) return;
    if (!confirm(`Remove "${zone.name}"?`)) return;
    try {
      await fetchJson(`/api/zones/${zone.id}`, { method: "DELETE" });
      await load();
    } catch {
      setError("Failed to remove place.");
    }
  }

  async function createZone() {
    if (!newZone.slug || !newZone.name) {
      setError("Name and slug are required.");
      return;
    }
    try {
      await fetchJson("/api/zones", {
        method: "POST",
        body: JSON.stringify(newZone),
      });
      setNewZone({
        slug: "",
        name: "",
        radius_meters: 75,
        enabled: true,
        zone_type: "custom",
        focus_mode: "",
        sort_order: 0,
      });
      setShowForm(false);
      setError("");
      await load();
    } catch {
      setError("Failed to create place.");
    }
  }

  return (
    <div className="zones-page">
      <div className="zones-header">
        <div>
          <span className="section-eyebrow">LOCATION INTELLIGENCE</span>
          <h2 className="zones-title">Places</h2>
        </div>
        <button
          className="log-intent-btn zones-add-btn"
          type="button"
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? "CANCEL" : "+ ADD PLACE"}
        </button>
      </div>

      {error && <div className="banner error">{error}</div>}

      {showForm && (
        <div className="zone-form">
          <span className="section-eyebrow">NEW PLACE</span>
          <div className="zone-form-fields">
            <div className="zone-field">
              <label>Name</label>
              <input
                className="zone-input"
                value={newZone.name ?? ""}
                onChange={(e) =>
                  setNewZone({ ...newZone, name: e.target.value })
                }
                placeholder="e.g. Home, Library"
              />
            </div>
            <div className="zone-field">
              <label>Slug</label>
              <input
                className="zone-input"
                value={newZone.slug ?? ""}
                onChange={(e) =>
                  setNewZone({
                    ...newZone,
                    slug: e.target.value
                      .toLowerCase()
                      .replace(/\s+/g, "-")
                      .replace(/[^a-z0-9-]/g, ""),
                  })
                }
                placeholder="e.g. home, library"
              />
            </div>
            <div className="zone-field">
              <label>Type</label>
              <select
                className="zone-input"
                value={newZone.zone_type ?? "custom"}
                onChange={(e) =>
                  setNewZone({ ...newZone, zone_type: e.target.value })
                }
              >
                <option value="custom">Custom</option>
                <option value="study">Study</option>
                <option value="work">Work</option>
                <option value="home">Home</option>
                <option value="gym">Gym</option>
              </select>
            </div>
            <div className="zone-field">
              <label>Radius (meters)</label>
              <input
                className="zone-input"
                type="number"
                min={25}
                max={500}
                value={newZone.radius_meters ?? 75}
                onChange={(e) =>
                  setNewZone({
                    ...newZone,
                    radius_meters: Number(e.target.value),
                  })
                }
              />
            </div>
          </div>
          <button
            className="log-intent-btn"
            type="button"
            style={{ marginTop: "1.5rem", width: "auto", padding: "0.75rem 2rem" }}
            onClick={() => void createZone()}
          >
            CREATE PLACE
          </button>
        </div>
      )}

      {loading ? (
        <div className="zones-loading">Loading places...</div>
      ) : zones.length === 0 ? (
        <div className="zones-empty">
          <p>No places configured yet.</p>
          <p className="muted">
            Add a place to enable location-aware tracking and iPhone automations.
          </p>
        </div>
      ) : (
        <div className="zones-list">
          {zones.map((zone) => (
            <div
              key={zone.id}
              className={`zone-card${zone.enabled ? "" : " zone-disabled"}`}
            >
              <div className="zone-card-header">
                <div>
                  <span className="zone-type-tag">
                    {zone.zone_type.toUpperCase()}
                  </span>
                  <h3 className="zone-name">{zone.name}</h3>
                  <span className="zone-slug">/{zone.slug}</span>
                </div>
                <div className="zone-card-actions">
                  <button
                    type="button"
                    className={`zone-toggle ${zone.enabled ? "zone-toggle-on" : "zone-toggle-off"}`}
                    onClick={() => void toggleZone(zone)}
                  >
                    {zone.enabled ? "ACTIVE" : "PAUSED"}
                  </button>
                  <button
                    type="button"
                    className="zone-delete"
                    onClick={() => void deleteZone(zone)}
                  >
                    REMOVE
                  </button>
                </div>
              </div>
              <div className="zone-card-meta">
                <span>RADIUS: {zone.radius_meters}m</span>
                {zone.focus_mode && (
                  <span>FOCUS: {zone.focus_mode.toUpperCase()}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── HistoryPage ───────────────────────────────────────────────────────────────

const CAL_HOURS = Array.from({ length: 24 }, (_, i) => i);

function calCellColor(s: HourlySummary | undefined): string {
  if (!s || s.productivity_score === null) return "var(--panel-strong)";
  if (s.productivity_score >= 7) return "var(--accent)";
  if (s.productivity_score >= 4) return "#f0b429";
  return "var(--bad)";
}

function HistoryPage({
  hourlySummaries,
  health,
  settings,
}: {
  hourlySummaries: HourlySummary[];
  health: HealthResponse | null;
  settings: BackendSettings | null;
}) {
  const [selected, setSelected] = useState<HourlySummary | null>(null);

  useEffect(() => {
    document.title = "Chronicle — History";
  }, []);

  // Build map: dateKey ("YYYY-MM-DD") → hour (0-23) → summary
  // Parse directly from ISO string to avoid browser TZ shifting
  const calMap = useMemo(() => {
    const map = new Map<string, Map<number, HourlySummary>>();
    for (const s of hourlySummaries) {
      const iso = s.hour_start_local;
      if (!iso || iso.length < 13) continue;
      const dateKey = iso.substring(0, 10);
      const hour = parseInt(iso.substring(11, 13), 10);
      if (!map.has(dateKey)) map.set(dateKey, new Map());
      map.get(dateKey)!.set(hour, s);
    }
    return map;
  }, [hourlySummaries]);

  // Last 7 calendar days based on browser local date
  const dayKeys = useMemo(() => {
    const days: string[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      days.push(
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
      );
    }
    return days;
  }, []);

  const todayKey = dayKeys[dayKeys.length - 1];

  function dayLabel(dateKey: string): string {
    if (dateKey === todayKey) return "Today";
    const d = new Date(`${dateKey}T12:00:00`);
    return d.toLocaleDateString([], {
      weekday: "short",
      month: "numeric",
      day: "numeric",
    });
  }

  return (
    <div className="history-page">
      <div className="history-status-strip">
        <div className="status-strip-item">
          <span className="status-strip-label">SERVICE</span>
          <span
            className={`status-strip-value ${
              health?.status === "ok" ? "value-good" : "value-bad"
            }`}
          >
            {health?.status?.toUpperCase() ?? "UNKNOWN"}
          </span>
        </div>
        <div className="status-strip-item">
          <span className="status-strip-label">LLM PROVIDER</span>
          <span className="status-strip-value">
            {health?.llm?.provider?.toUpperCase() ?? "—"}
          </span>
        </div>
        <div className="status-strip-item">
          <span className="status-strip-label">TRACKING</span>
          <span
            className={`status-strip-value ${
              settings?.tracking_enabled ? "value-good" : "value-warn"
            }`}
          >
            {settings?.tracking_enabled ? "ENABLED" : "PAUSED"}
          </span>
        </div>
        {health?.uptime_seconds !== undefined && (
          <div className="status-strip-item">
            <span className="status-strip-label">UPTIME</span>
            <span className="status-strip-value">
              {Math.floor(health.uptime_seconds / 3600)}h{" "}
              {Math.floor((health.uptime_seconds % 3600) / 60)}m
            </span>
          </div>
        )}
      </div>

      <div className="history-content">
        <div className="history-header">
          <span className="section-eyebrow">7-DAY CHRONICLE</span>
          <h2 className="history-title">Session History</h2>
        </div>

        <div className="cal-scroll-wrap">
          <div className="cal-grid">
            {/* Hour axis labels */}
            <div className="cal-hour-axis">
              <div className="cal-axis-header" />
              {CAL_HOURS.map((h) => (
                <div key={h} className="cal-axis-cell">
                  {h % 3 === 0 && (
                    <span className="cal-hour-label">
                      {h === 0
                        ? "12a"
                        : h < 12
                          ? `${h}a`
                          : h === 12
                            ? "12p"
                            : `${h - 12}p`}
                    </span>
                  )}
                </div>
              ))}
            </div>

            {/* Day columns */}
            {dayKeys.map((dateKey) => (
              <div key={dateKey} className="cal-day-col">
                <div
                  className={`cal-col-header${dateKey === todayKey ? " cal-today-header" : ""}`}
                >
                  {dayLabel(dateKey)}
                </div>
                {CAL_HOURS.map((h) => {
                  const s = calMap.get(dateKey)?.get(h);
                  const isSelected = selected?.id === s?.id && !!s;
                  return (
                    <div
                      key={h}
                      className={`cal-hour-cell${s ? " cal-has-data" : ""}${isSelected ? " cal-selected" : ""}`}
                      style={{ background: calCellColor(s) }}
                      title={
                        s
                          ? `${formatHour(s.hour_start_local)}: ${productivityGrade(Math.round((s.productivity_score ?? 0) * 10))} (${Math.round((s.productivity_score ?? 0) * 10)}%)`
                          : undefined
                      }
                      onClick={() =>
                        s
                          ? setSelected(isSelected ? null : s)
                          : undefined
                      }
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {/* Legend */}
        <div className="cal-legend">
          <span className="cal-legend-item">
            <span
              className="cal-legend-dot"
              style={{ background: "var(--accent)" }}
            />
            HIGH (7–10)
          </span>
          <span className="cal-legend-item">
            <span
              className="cal-legend-dot"
              style={{ background: "#f0b429" }}
            />
            MID (4–7)
          </span>
          <span className="cal-legend-item">
            <span
              className="cal-legend-dot"
              style={{ background: "var(--bad)" }}
            />
            LOW (0–4)
          </span>
          <span className="cal-legend-item">
            <span
              className="cal-legend-dot"
              style={{ background: "var(--panel-strong)" }}
            />
            NO DATA
          </span>
        </div>

        {/* Selected hour detail */}
        {selected && (() => {
          const pct = Math.round((selected.productivity_score ?? 0) * 10);
          const g = productivityGrade(pct);
          return (
            <div className="cal-detail-panel">
              <div className="cal-detail-header">
                <span className="timeline-hour">
                  {formatHour(selected.hour_start_local)}
                </span>
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: "0.5rem",
                  }}
                >
                  <span
                    className="timeline-grade"
                    style={{ color: gradeColor(g) }}
                  >
                    {g}
                  </span>
                  <span className="timeline-score">{pct}%</span>
                </div>
                <button
                  className="cal-detail-close"
                  type="button"
                  onClick={() => setSelected(null)}
                >
                  ✕
                </button>
              </div>
              <p className="timeline-summary">{selected.summary_text}</p>
            </div>
          );
        })()}

        {hourlySummaries.length === 0 && (
          <div className="history-empty">
            <p>No hourly summaries yet.</p>
            <p className="muted">
              Summaries are generated automatically each hour as you work.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Surface & Field ───────────────────────────────────────────────────────────

function Surface({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
}) {
  return (
    <section className="surface">
      <div style={{ marginBottom: "2rem" }}>
        {eyebrow && <div className="section-eyebrow">{eyebrow}</div>}
        <h2
          style={{
            fontFamily: "Newsreader",
            fontSize: "2.5rem",
            fontStyle: "italic",
            fontWeight: 300,
            margin: 0,
          }}
        >
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "1.25rem 0",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <span
        style={{
          fontSize: "0.7rem",
          fontWeight: 800,
          letterSpacing: "0.1em",
          color: "var(--muted)",
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: "0.9rem", fontWeight: 500 }}>
        {String(value ?? "—")}
      </span>
    </div>
  );
}

// ── SettingsPage ──────────────────────────────────────────────────────────────

function SettingsPage({
  settings,
  onSave,
}: {
  settings: BackendSettings | null;
  onSave: (s: BackendSettings) => Promise<void>;
}) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<BackendSettings | null>(settings);
  useEffect(() => {
    setDraft(settings);
  }, [settings]);
  if (!draft) return null;
  return (
    <div style={{ padding: "2rem" }}>
      <Surface title="System Settings" eyebrow="Configuration">
        <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
          <label
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>Tracking Enabled</span>
            <input
              type="checkbox"
              checked={draft.tracking_enabled}
              onChange={(e) =>
                setDraft({ ...draft, tracking_enabled: e.target.checked })
              }
            />
          </label>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              paddingTop: "0.5rem",
              borderTop: "1px solid var(--line)",
            }}
          >
            <div>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.08em", color: "var(--muted)" }}>TIMEZONE</div>
              <div style={{ fontSize: "0.9rem", marginTop: "0.25rem" }}>{draft.user_timezone}</div>
            </div>
            <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>
              Auto-synced from browser
            </span>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              paddingTop: "0.5rem",
              borderTop: "1px solid var(--line)",
            }}
          >
            <div>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.08em", color: "var(--muted)" }}>LOCATION ZONES</div>
              <div style={{ fontSize: "0.85rem", color: "var(--text-soft)", marginTop: "0.25rem" }}>
                Manage iPhone geofence zones
              </div>
            </div>
            <button
              className="channel-btn"
              type="button"
              onClick={() => navigate("/zones")}
            >
              MANAGE →
            </button>
          </div>
          <button
            className="log-intent-btn"
            type="button"
            style={{ width: "auto", padding: "1rem 2rem" }}
            onClick={() => void onSave(draft)}
          >
            Save Changes
          </button>
        </div>
      </Surface>
    </div>
  );
}

// ── App Root ──────────────────────────────────────────────────────────────────

export default function App() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [settings, setSettings] = useState<BackendSettings | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [hourlySummaries, setHourlySummaries] = useState<HourlySummary[]>([]);
  const [aiDayInsight, setAiDayInsight] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function refreshCore() {
    setRefreshing(true);
    try {
      const [st, se, an, lo, hs, ai, he] = await Promise.allSettled([
        fetchJson<DashboardState>("/api/state"),
        fetchJson<BackendSettings>("/api/settings"),
        fetchJson<Analytics>("/api/analytics/today"),
        fetchJson<ActivityLog[]>("/api/logs?limit=15"),
        fetchJson<HourlySummary[]>("/api/hourly-summaries?limit=168"),
        fetchJson<{ ai_day_insight?: string }>("/api/calendar/today"),
        fetchJson<HealthResponse>("/api/healthz"),
      ]);
      if (st.status === "fulfilled") setState(st.value);
      if (se.status === "fulfilled") {
        setSettings(se.value);
        // Auto-sync browser timezone to backend if it differs
        const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (browserTz && se.value.user_timezone !== browserTz) {
          fetchJson("/api/settings", {
            method: "POST",
            body: JSON.stringify({ user_timezone: browserTz }),
          }).catch(() => {});
        }
      }
      if (an.status === "fulfilled") setAnalytics(an.value);
      if (lo.status === "fulfilled") setLogs(lo.value);
      if (hs.status === "fulfilled") setHourlySummaries(hs.value);
      if (ai.status === "fulfilled")
        setAiDayInsight(ai.value.ai_day_insight ?? null);
      if (he.status === "fulfilled") setHealth(he.value);
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void refreshCore();
    const i = setInterval(() => {
      if (!document.hidden) void refreshCore();
    }, 60000);
    return () => clearInterval(i);
  }, []);

  return (
    <BrowserRouter>
      <AppShell
        statusMessage={statusMessage}
        errorMessage={errorMessage}
        refreshing={refreshing}
        onRefresh={() => void refreshCore()}
        state={state}
        logs={logs}
      >
        <Routes>
          <Route path="/" element={<Navigate replace to="/today" />} />
          <Route
            path="/today"
            element={
              <TodayPage
                state={state}
                analytics={analytics}
                logs={logs}
                hourlySummaries={hourlySummaries}
                aiDayInsight={aiDayInsight}
                onRefreshLogs={refreshCore}
              />
            }
          />
          <Route path="/zones" element={<ZonesPage />} />
          <Route
            path="/diagnostics"
            element={
              <HistoryPage
                hourlySummaries={hourlySummaries}
                health={health}
                settings={settings}
              />
            }
          />
          <Route
            path="/settings"
            element={
              <SettingsPage
                settings={settings}
                onSave={async (s) => {
                  await fetchJson("/api/settings", {
                    method: "POST",
                    body: JSON.stringify(s),
                  });
                  setStatusMessage("Settings updated.");
                  void refreshCore();
                }}
              />
            }
          />
          <Route path="*" element={<Navigate replace to="/today" />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
