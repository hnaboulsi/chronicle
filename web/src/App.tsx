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
  sleep_start_hour: number;
  sleep_end_hour: number;
};

type CalendarEvent = {
  id: number;
  title: string;
  start_at: string;
  end_at: string;
  calendar_name?: string;
  is_current: boolean;
  is_past: boolean;
  event_type: string;
  event_note: string | null;
  ai_brief: string | null;
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

type CheckinPayload = {
  checkin: string | null;
  guess: string;
  age_seconds: number | null;
  event_title: string | null;
  event_location: string | null;
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


function productivePulseData(hourlySummaries: HourlySummary[]) {
  // Only use real today summaries with actual scores, sorted chronologically,
  // excluding sleep stubs (summary_text "Likely sleeping")
  const todayKey = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  })();
  const real = hourlySummaries
    .filter(
      (s) =>
        s.hour_start_local?.startsWith(todayKey) &&
        s.productivity_score !== null &&
        !s.summary_text?.startsWith("Likely sleeping") &&
        !s.summary_text?.startsWith("No Mac activity")
    )
    .sort(
      (a, b) =>
        new Date(a.hour_start_local).getTime() -
        new Date(b.hour_start_local).getTime()
    )
    .map((s) => Math.round((s.productivity_score ?? 0) * 10));
  return real;
}

function formatTimestamp(ts: string): string {
  // Backend returns naive UTC strings (no Z/offset); append Z so the browser
  // parses them as UTC then converts to local time via toLocaleTimeString.
  const normalized = ts && !ts.endsWith("Z") && !ts.includes("+") ? ts + "Z" : ts;
  return new Date(normalized).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

function formatHour(ts: string): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "numeric",
    hour12: true,
  });
}

// ── NavItem ────────────────────────────────────────────────────────────────────

function NavItem({ to, label, dim, badge }: { to: string; label: string; dim?: boolean; badge?: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `nav-item${dim ? " nav-dim" : ""}${isActive ? " active" : ""}`
      }
    >
      {label}
      {badge && <span className="nav-badge" />}
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
  hasCheckin,
  lastRefreshed,
}: {
  children: ReactNode;
  statusMessage: string;
  errorMessage: string;
  refreshing: boolean;
  onRefresh: () => void;
  state: DashboardState | null;
  logs: ActivityLog[];
  hasCheckin: boolean;
  lastRefreshed: Date | null;
}) {
  const [logPanelOpen, setLogPanelOpen] = useState(false);
  const [syncAge, setSyncAge] = useState<string>("");
  const navigate = useNavigate();

  useEffect(() => {
    if (!lastRefreshed) return;
    function updateAge() {
      const secs = Math.round((Date.now() - lastRefreshed!.getTime()) / 1000);
      if (secs < 60) setSyncAge(`${secs}s AGO`);
      else setSyncAge(`${Math.floor(secs / 60)}m AGO`);
    }
    updateAge();
    const t = setInterval(updateAge, 10000);
    return () => clearInterval(t);
  }, [lastRefreshed]);

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
          <NavItem to="/today" label="Today" badge={hasCheckin} />
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
            {syncAge && !refreshing && (
              <span className="topbar-sync">SYNCED {syncAge}</span>
            )}
            <button
              className="refresh-btn"
              onClick={onRefresh}
              type="button"
              disabled={refreshing}
            >
              {refreshing ? "SYNCHRONIZING..." : "REFRESH"}
            </button>
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

function eventTypeColor(type: string): string {
  switch (type) {
    case "lecture": return "var(--warn)";
    case "exam": return "var(--bad)";
    case "flight": return "#60a5fa";
    case "assignment": return "var(--accent)";
    case "meeting": return "var(--text-soft)";
    default: return "var(--muted)";
  }
}

function eventTypeLabel(type: string): string {
  switch (type) {
    case "lecture": return "CLASS";
    case "assignment": return "HOMEWORK";
    case "exam": return "EXAM";
    case "meeting": return "MEETING";
    case "flight": return "FLIGHT";
    default: return type.toUpperCase();
  }
}

function getRecentFocusLabels(categoryMinutes: Record<string, number>): string[] {
  return Object.entries(categoryMinutes)
    .filter(([, mins]) => mins > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([cat]) => cat.replace(/_/g, " "));
}

function deriveScheduleLabel(events: CalendarEvent[]): string {
  const types = new Set(events.map((e) => e.event_type));
  if (types.has("lecture") && types.has("meeting")) return "CLASSES & MEETINGS";
  if (types.has("lecture")) return "CLASS SCHEDULE";
  if (types.has("meeting")) return "MEETINGS";
  if (types.has("assignment") || types.has("exam")) return "UPCOMING TASKS";
  return "TODAY'S SCHEDULE";
}

function TodayPage({
  state,
  analytics,
  hourlySummaries,
  aiDayInsight,
  calendarEvents,
  nudge,
  onDismissNudge,
  checkin,
  onCheckinAction,
  onRefreshLogs,
}: {
  state: DashboardState | null;
  analytics: Analytics | null;
  hourlySummaries: HourlySummary[];
  aiDayInsight?: string | null;
  calendarEvents: CalendarEvent[];
  nudge: { text: string; category: string } | null;
  onDismissNudge: () => void;
  checkin: CheckinPayload | null;
  onCheckinAction: () => void;
  onRefreshLogs: () => void;
}) {
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [checkinInput, setCheckinInput] = useState("");
  const [checkinLoading, setCheckinLoading] = useState(false);
  const [nudgeLoading, setNudgeLoading] = useState(false);

  useEffect(() => {
    document.title = state?.mac_idle ? "Chronicle (Idle)" : "Chronicle";
  }, [state?.mac_idle]);

  // "/" hotkey focuses the intent input
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/") return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      (document.getElementById("intent-input") as HTMLInputElement | null)?.focus();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  async function handleCheckin(action: "confirm" | "snooze" | "dismiss") {
    setCheckinLoading(true);
    try {
      if (action === "confirm") {
        await fetchJson("/api/checkin/confirm", {
          method: "POST",
          body: JSON.stringify(checkinInput.trim()
            ? { confirmed: false, correction: checkinInput.trim() }
            : { confirmed: true }),
        });
      } else if (action === "snooze") {
        await fetchJson("/api/checkin/snooze", { method: "POST", body: JSON.stringify({ minutes: 30 }) });
      } else {
        await fetchJson("/api/checkin/dismiss", { method: "POST" });
      }
      setCheckinInput("");
      onCheckinAction();
    } finally {
      setCheckinLoading(false);
    }
  }

  async function handleDismissNudge() {
    setNudgeLoading(true);
    try { await onDismissNudge(); } finally { setNudgeLoading(false); }
  }

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

  const pulseValues = productivePulseData(hourlySummaries);
  const grade = productivityGrade(analytics?.productive_pct ?? 0);
  const gColor = gradeColor(grade);

  // For pulse time labels use only today's real summaries (same filter as bar chart)
  const todayKey = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  })();
  const sortedSummaries = hourlySummaries
    .filter(
      (s) =>
        s.hour_start_local?.startsWith(todayKey) &&
        s.productivity_score !== null &&
        !s.summary_text?.startsWith("Likely sleeping") &&
        !s.summary_text?.startsWith("No Mac activity")
    )
    .sort(
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

  // Upcoming events: not past, sorted by start time
  const now = new Date();
  const upcomingEvents = calendarEvents
    .filter((e) => !e.is_past || e.is_current)
    .sort((a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime());
  const scheduleLabel = deriveScheduleLabel(upcomingEvents);

  const categoryMinutes = analytics?.category_minutes ?? {};
  const categoryEntries = Object.entries(categoryMinutes)
    .filter(([, mins]) => mins > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);
  const totalMins = Math.max(analytics?.total_active_minutes ?? 0, 1);
  const productiveCategories = new Set(["studying", "working", "creative"]);
  const topFocusCategories = getRecentFocusLabels(categoryMinutes);

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

            {topFocusCategories.length > 0 && (
              <div className="recent-channels">
                <span className="section-eyebrow">RECENT FOCUS</span>
                <div className="channel-btns">
                  {topFocusCategories.map((cat) => (
                    <button
                      key={cat}
                      className="channel-btn"
                      type="button"
                      onClick={() => setChatInput(cat)}
                    >
                      {cat.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

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
            <span className="card-subtitle">
              {pulseValues.length > 0
                ? `${pulseValues.length} HOUR${pulseValues.length === 1 ? "" : "S"} TRACKED TODAY`
                : "NO DATA YET TODAY"}
            </span>
            {pulseValues.length > 0 ? (
              <>
                <div className="pulse-bars">
                  {pulseValues.map((v, i) => (
                    <div
                      key={i}
                      className="pulse-bar-item"
                      style={{
                        height: `${Math.max(4, v)}%`,
                        background: v >= 70 ? "var(--accent)" : v >= 40 ? "#f0b429" : "var(--bad)",
                        opacity: v === 0 ? 0.25 : 0.85,
                      }}
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
              </>
            ) : (
              <div
                style={{
                  height: 60,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--muted)",
                  fontSize: "0.7rem",
                  letterSpacing: "0.08em",
                }}
              >
                Tracking will begin once activity is recorded
              </div>
            )}
            {categoryEntries.length > 0 && (
              <div className="category-breakdown">
                {categoryEntries.map(([cat, mins]) => (
                  <div key={cat} className="category-row">
                    <span className="category-name">{cat.replace(/_/g, " ").toUpperCase()}</span>
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
                  OUTPUT: {analytics?.log_count ?? 0} LOGS
                </span>
              </div>
            </div>
          </article>

          {/* Check-in prompt card */}
          {checkin?.checkin && (
            <div className="checkin-card">
              <span className="section-eyebrow" style={{ color: "var(--accent)" }}>CHECK-IN</span>
              <p className="checkin-question">{checkin.checkin}</p>
              <input
                className="checkin-input"
                placeholder={checkin.guess ? `"${checkin.guess}" — or type a correction` : "What are you working on?"}
                value={checkinInput}
                onChange={(e) => setCheckinInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void handleCheckin("confirm"); }}
              />
              <div className="checkin-actions">
                <button type="button" className={`checkin-btn checkin-btn-confirm${checkinLoading ? " btn-processing" : ""}`} disabled={checkinLoading} onClick={() => void handleCheckin("confirm")}>
                  ✓ CONFIRM
                </button>
                <button type="button" className={`checkin-btn checkin-btn-snooze${checkinLoading ? " btn-processing" : ""}`} disabled={checkinLoading} onClick={() => void handleCheckin("snooze")}>
                  SNOOZE 30m
                </button>
                <button type="button" className={`checkin-btn checkin-btn-dismiss${checkinLoading ? " btn-processing" : ""}`} disabled={checkinLoading} onClick={() => void handleCheckin("dismiss")}>
                  DISMISS
                </button>
              </div>
            </div>
          )}

          {/* Tonight / Today's remaining events */}
          <article className="editorial-card tonight-events">
            <span className="section-eyebrow">{scheduleLabel}</span>
            {upcomingEvents.length === 0 ? (
              <p className="tonight-empty">No remaining events today.</p>
            ) : (
              <div className="tonight-list">
                {upcomingEvents.map((ev) => (
                  <div key={ev.id} className="tonight-row">
                    <span
                      className="tonight-dot"
                      style={{ background: eventTypeColor(ev.event_type) }}
                    />
                    <div className="tonight-details">
                      <div className="tonight-title">{ev.title}</div>
                      <div className="tonight-meta">
                        <span className="tonight-time">
                          {new Date(ev.start_at).toLocaleTimeString([], {
                            hour: "numeric",
                            minute: "2-digit",
                            hour12: true,
                          })}
                        </span>
                        {ev.calendar_name && (
                          <span className="tonight-cal">{ev.calendar_name}</span>
                        )}
                        {ev.is_current && (
                          <span className="tonight-now">NOW</span>
                        )}
                      </div>
                      {ev.event_note && (
                        <div className="tonight-note">{ev.event_note}</div>
                      )}
                    </div>
                    <span className="tonight-type">
                      {eventTypeLabel(ev.event_type)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </article>

          {nudge && (
            <div className="nudge-banner">
              <span className="nudge-text">{nudge.text}</span>
              <button
                className={`nudge-dismiss${nudgeLoading ? " btn-processing" : ""}`}
                type="button"
                onClick={() => void handleDismissNudge()}
                disabled={nudgeLoading}
                aria-label="Dismiss"
              >
                ✕
              </button>
            </div>
          )}

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
  const [processingZoneId, setProcessingZoneId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [newZone, setNewZone] = useState<Partial<ZoneRecord>>({
    slug: "",
    name: "",
    radius_meters: 75,
    enabled: true,
    zone_type: "custom",
    focus_mode: "",
    sort_order: 0,
  });
  const [editingZoneId, setEditingZoneId] = useState<number | null>(null);
  const [editZone, setEditZone] = useState<Partial<ZoneRecord>>({});

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
    setProcessingZoneId(zone.id);
    try {
      await fetchJson(`/api/zones/${zone.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !zone.enabled }),
      });
      await load();
    } catch {
      setError("Failed to update place.");
    } finally {
      setProcessingZoneId(null);
    }
  }

  async function deleteZone(zone: ZoneRecord) {
    if (!zone.id) return;
    if (!confirm(`Remove "${zone.name}"?`)) return;
    setProcessingZoneId(zone.id);
    try {
      await fetchJson(`/api/zones/${zone.id}`, { method: "DELETE" });
      await load();
    } catch {
      setError("Failed to remove place.");
    } finally {
      setProcessingZoneId(null);
    }
  }

  async function createZone() {
    if (!newZone.slug || !newZone.name) {
      setError("Name and slug are required.");
      return;
    }
    setCreating(true);
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
    } finally {
      setCreating(false);
    }
  }

  async function saveZoneEdit(zone: ZoneRecord) {
    if (!zone.id) return;
    setProcessingZoneId(zone.id);
    try {
      await fetchJson(`/api/zones/${zone.id}`, {
        method: "PATCH",
        body: JSON.stringify(editZone),
      });
      setEditingZoneId(null);
      setEditZone({});
      setError("");
      await load();
    } catch {
      setError("Failed to update place.");
    } finally {
      setProcessingZoneId(null);
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
          </div>
          <button
            className={`log-intent-btn${creating ? " btn-processing" : ""}`}
            type="button"
            style={{ marginTop: "1.5rem", width: "auto", padding: "0.75rem 2rem" }}
            disabled={creating}
            onClick={() => void createZone()}
          >
            {creating ? "CREATING..." : "CREATE PLACE"}
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
                    className={`zone-toggle ${zone.enabled ? "zone-toggle-on" : "zone-toggle-off"}${processingZoneId === zone.id ? " btn-processing" : ""}`}
                    disabled={processingZoneId === zone.id}
                    onClick={() => void toggleZone(zone)}
                  >
                    {zone.enabled ? "ACTIVE" : "PAUSED"}
                  </button>
                  <button
                    type="button"
                    className="zone-edit-btn"
                    onClick={() => {
                      if (editingZoneId === zone.id) {
                        setEditingZoneId(null);
                        setEditZone({});
                      } else {
                        setEditingZoneId(zone.id ?? null);
                        setEditZone({
                          name: zone.name,
                          zone_type: zone.zone_type,
                          radius_meters: zone.radius_meters,
                          focus_mode: zone.focus_mode,
                        });
                      }
                    }}
                  >
                    {editingZoneId === zone.id ? "CANCEL" : "EDIT"}
                  </button>
                  <button
                    type="button"
                    className={`zone-delete${processingZoneId === zone.id ? " btn-processing" : ""}`}
                    disabled={processingZoneId === zone.id}
                    onClick={() => void deleteZone(zone)}
                  >
                    REMOVE
                  </button>
                </div>
              </div>
              {editingZoneId === zone.id && (
                <div className="zone-edit-form">
                  <div className="zone-form-fields">
                    <div className="zone-field">
                      <label>Name</label>
                      <input className="zone-input" value={editZone.name ?? ""} onChange={(e) => setEditZone({ ...editZone, name: e.target.value })} />
                    </div>
                    <div className="zone-field">
                      <label>Type</label>
                      <select className="zone-input" value={editZone.zone_type ?? "custom"} onChange={(e) => setEditZone({ ...editZone, zone_type: e.target.value })}>
                        <option value="custom">Custom</option>
                        <option value="study">Study</option>
                        <option value="work">Work</option>
                        <option value="home">Home</option>
                        <option value="gym">Gym</option>
                      </select>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
                    <button type="button" className={`log-intent-btn${processingZoneId === zone.id ? " btn-processing" : ""}`} style={{ flex: 1, padding: "0.6rem" }} disabled={processingZoneId === zone.id} onClick={() => void saveZoneEdit(zone)}>{processingZoneId === zone.id ? "SAVING..." : "SAVE CHANGES"}</button>
                    <button type="button" className="zone-delete" style={{ padding: "0.6rem 1rem" }} onClick={() => { setEditingZoneId(null); setEditZone({}); }}>CANCEL</button>
                  </div>
                </div>
              )}
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
  const [expandedDay, setExpandedDay] = useState<string | null>(null);

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

        {/* Day Chronicle Cards — newest first */}
        <div className="chronicle-view">
          {[...dayKeys].reverse().map((dateKey) => {
            const realSummaries = Array.from(calMap.get(dateKey)?.values() ?? [])
              .filter(
                (s) =>
                  s.productivity_score !== null &&
                  !s.summary_text?.startsWith("Likely sleeping") &&
                  !s.summary_text?.startsWith("No Mac activity")
              )
              .sort((a, b) => b.hour_start_local.localeCompare(a.hour_start_local));

            const dayAvg =
              realSummaries.length > 0
                ? Math.round(
                    realSummaries.reduce(
                      (sum, s) => sum + (s.productivity_score ?? 0) * 10,
                      0
                    ) / realSummaries.length
                  )
                : null;
            const dayGrade = dayAvg !== null ? productivityGrade(dayAvg) : null;

            const headline = [...realSummaries].sort(
              (a, b) => (b.productivity_score ?? 0) - (a.productivity_score ?? 0)
            )[0];

            const isExpanded = expandedDay === dateKey;
            const isToday = dateKey === todayKey;

            return (
              <div
                key={dateKey}
                className={`chronicle-card${isToday ? " chronicle-today" : ""}`}
              >
                <div
                  className="chronicle-card-header"
                  onClick={() => setExpandedDay(isExpanded ? null : dateKey)}
                >
                  <div className="chronicle-card-meta">
                    <span
                      className={`chronicle-day-name${isToday ? " chronicle-today-name" : ""}`}
                    >
                      {isToday ? "TODAY · " : ""}
                      {dayLabel(dateKey).toUpperCase()}
                    </span>
                    <div className="chronicle-card-right">
                      {dayGrade && (
                        <span
                          className="chronicle-grade"
                          style={{ color: gradeColor(dayGrade) }}
                        >
                          {dayGrade} · {dayAvg}%
                        </span>
                      )}
                      <button type="button" className="chronicle-expand-btn">
                        {isExpanded
                          ? "↑ COLLAPSE"
                          : `↓ ${realSummaries.length} HOUR${realSummaries.length !== 1 ? "S" : ""}`}
                      </button>
                    </div>
                  </div>

                  {/* Sparkline: 24 bars proportional to productivity score */}
                  <div className="chronicle-sparkline">
                    {CAL_HOURS.map((h) => {
                      const s = calMap.get(dateKey)?.get(h);
                      const score = s?.productivity_score ?? null;
                      const isSleep = s?.summary_text?.startsWith("Likely sleeping");
                      return (
                        <div
                          key={h}
                          className="chronicle-spark-bar"
                          style={{
                            height:
                              score !== null && !isSleep
                                ? `${Math.max(20, score * 10)}%`
                                : "15%",
                            background: isSleep ? "transparent" : calCellColor(s),
                            opacity: score !== null && !isSleep ? 0.85 : 0.15,
                          }}
                        />
                      );
                    })}
                  </div>

                  {headline ? (
                    <p className="chronicle-headline">"{headline.summary_text}"</p>
                  ) : (
                    <p className="chronicle-empty-day">No activity recorded.</p>
                  )}
                </div>

                {isExpanded && realSummaries.length > 0 && (
                  <div className="chronicle-hours">
                    {realSummaries.map((s) => {
                      const pct = Math.round((s.productivity_score ?? 0) * 10);
                      const g = productivityGrade(pct);
                      return (
                        <div key={s.id} className="chronicle-hour-row">
                          <div className="chronicle-hour-time">
                            {formatHour(s.hour_start_local)}
                          </div>
                          <span
                            className="chronicle-hour-grade"
                            style={{ color: gradeColor(g) }}
                          >
                            {g}
                          </span>
                          <div className="chronicle-hour-bar">
                            <div
                              className="chronicle-hour-fill"
                              style={{
                                width: `${pct}%`,
                                background:
                                  pct >= 70
                                    ? "var(--accent)"
                                    : pct >= 40
                                    ? "#f0b429"
                                    : "var(--bad)",
                              }}
                            />
                          </div>
                          <p className="chronicle-hour-text">{s.summary_text}</p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

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

const CAPTURE_INTERVALS = [
  { label: "5 min", value: 300 },
  { label: "15 min", value: 900 },
  { label: "30 min", value: 1800 },
];

function SettingsPage({
  settings,
  onSave,
}: {
  settings: BackendSettings | null;
  onSave: (s: BackendSettings & { calendar_ical_urls: string[] }) => Promise<void>;
}) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<BackendSettings | null>(settings);
  const [calUrls, setCalUrls] = useState<string[]>(settings?.calendar_ical_urls ?? []);
  const [newUrl, setNewUrl] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(settings);
    setCalUrls(settings?.calendar_ical_urls ?? []);
  }, [settings]);

  if (!draft) return null;

  // Round capture interval to nearest preset for display
  const nearestInterval =
    CAPTURE_INTERVALS.reduce((prev, curr) =>
      Math.abs(curr.value - draft.capture_interval_seconds) <
      Math.abs(prev.value - draft.capture_interval_seconds)
        ? curr
        : prev
    ).value;

  function addUrl() {
    const url = newUrl.trim();
    if (url && !calUrls.includes(url)) {
      setCalUrls([...calUrls, url]);
      setNewUrl("");
    }
  }

  function removeUrl(url: string) {
    setCalUrls(calUrls.filter((u) => u !== url));
  }

  return (
    <div style={{ padding: "2rem" }}>
      <Surface title="System Settings" eyebrow="Configuration">
        <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>

          {/* Tracking toggle */}
          <label className="settings-row">
            <span className="settings-label">Tracking Enabled</span>
            <input
              type="checkbox"
              checked={draft.tracking_enabled}
              onChange={(e) =>
                setDraft({ ...draft, tracking_enabled: e.target.checked })
              }
            />
          </label>

          {/* Capture interval */}
          <div className="settings-section">
            <div className="settings-label">CAPTURE INTERVAL</div>
            <div className="settings-sublabel">How often the Mac app records activity</div>
            <div className="capture-interval-group">
              {CAPTURE_INTERVALS.map(({ label, value }) => (
                <button
                  key={value}
                  type="button"
                  className={`interval-btn${nearestInterval === value ? " interval-btn-active" : ""}`}
                  onClick={() =>
                    setDraft({ ...draft, capture_interval_seconds: value })
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Sleep hours */}
          <div className="settings-section">
            <div className="settings-label">SLEEP WINDOW</div>
            <div className="settings-sublabel">No LLM calls or check-ins during these hours</div>
            <div className="sleep-hours-row">
              <div className="sleep-hour-field">
                <span>From</span>
                <input
                  type="number"
                  min={0}
                  max={23}
                  className="sleep-hour-input"
                  value={draft.sleep_start_hour ?? 1}
                  onChange={(e) =>
                    setDraft({ ...draft, sleep_start_hour: Number(e.target.value) })
                  }
                />
                <span>:00</span>
              </div>
              <div className="sleep-hour-field">
                <span>To</span>
                <input
                  type="number"
                  min={0}
                  max={23}
                  className="sleep-hour-input"
                  value={draft.sleep_end_hour ?? 9}
                  onChange={(e) =>
                    setDraft({ ...draft, sleep_end_hour: Number(e.target.value) })
                  }
                />
                <span>:00</span>
              </div>
            </div>
          </div>

          {/* Calendar iCal URLs */}
          <div className="settings-section">
            <div className="settings-label">CALENDAR FEEDS</div>
            <div className="settings-sublabel">iCal (.ics) subscription URLs</div>
            {calUrls.length > 0 && (
              <div className="ical-list">
                {calUrls.map((url) => (
                  <div key={url} className="ical-row">
                    <span className="ical-url">{url}</span>
                    <button
                      type="button"
                      className="ical-remove"
                      onClick={() => removeUrl(url)}
                    >
                      REMOVE
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="ical-add-row">
              <input
                className="zone-input ical-input"
                placeholder="https://..."
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addUrl()}
              />
              <button
                type="button"
                className="channel-btn"
                onClick={addUrl}
              >
                ADD
              </button>
            </div>
          </div>

          {/* Timezone (read-only, auto-synced) */}
          <div className="settings-section">
            <div className="settings-label">TIMEZONE</div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "0.9rem" }}>{draft.user_timezone}</span>
              <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>Auto-synced</span>
            </div>
          </div>

          {/* Location zones link */}
          <div className="settings-row">
            <div>
              <div className="settings-label">LOCATION ZONES</div>
              <div className="settings-sublabel">Manage iPhone geofence zones</div>
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
            className={`log-intent-btn${saving ? " btn-processing" : ""}`}
            type="button"
            style={{ width: "auto", padding: "1rem 2rem" }}
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try { await onSave({ ...draft, calendar_ical_urls: calUrls }); }
              finally { setSaving(false); }
            }}
          >
            {saving ? "Saving..." : "Save Changes"}
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
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [nudge, setNudge] = useState<{ text: string; category: string } | null>(null);
  const [checkin, setCheckin] = useState<CheckinPayload | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function refreshCore() {
    setRefreshing(true);
    try {
      const [st, se, an, lo, hs, ai, he, ca, ci] = await Promise.allSettled([
        fetchJson<DashboardState>("/api/state"),
        fetchJson<BackendSettings>("/api/settings"),
        fetchJson<Analytics>("/api/analytics/today"),
        fetchJson<ActivityLog[]>("/api/logs?limit=15"),
        fetchJson<HourlySummary[]>("/api/hourly-summaries?limit=168"),
        fetchJson<{ ai_day_insight?: string; events?: CalendarEvent[] }>("/api/calendar/today"),
        fetchJson<HealthResponse>("/api/healthz"),
        fetchJson<{ callout: string | null; category?: string }>("/api/callout"),
        fetchJson<CheckinPayload>("/api/checkin"),
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
      if (ai.status === "fulfilled") {
        setAiDayInsight(ai.value.ai_day_insight ?? null);
        setCalendarEvents(ai.value.events ?? []);
      }
      if (he.status === "fulfilled") setHealth(he.value);
      if (ca.status === "fulfilled" && ca.value.callout) {
        setNudge({ text: ca.value.callout, category: ca.value.category ?? "" });
      } else if (ca.status === "fulfilled" && !ca.value.callout) {
        setNudge(null);
      }
      if (ci.status === "fulfilled" && ci.value.checkin) {
        setCheckin(ci.value);
      } else if (ci.status === "fulfilled" && !ci.value.checkin) {
        setCheckin(null);
      }
      setLastRefreshed(new Date());
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
        hasCheckin={!!checkin?.checkin}
        lastRefreshed={lastRefreshed}
      >
        <Routes>
          <Route path="/" element={<Navigate replace to="/today" />} />
          <Route
            path="/today"
            element={
              <TodayPage
                state={state}
                analytics={analytics}
                hourlySummaries={hourlySummaries}
                aiDayInsight={aiDayInsight}
                calendarEvents={calendarEvents}
                nudge={nudge}
                onDismissNudge={async () => {
                  await fetchJson("/api/callout/dismiss", { method: "POST" });
                  setNudge(null);
                }}
                checkin={checkin}
                onCheckinAction={() => setCheckin(null)}
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
