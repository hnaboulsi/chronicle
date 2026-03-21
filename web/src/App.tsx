import React, {
  startTransition,
  useDeferredValue,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

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

type ContextSummary = {
  facts: string[];
  current_self_report: string;
  current_location: string;
  activity_category: string;
  activity_summary: string;
  presence: string;
  pending_checkin: string | null;
  zone_lock_active: boolean;
  zone_lock_until: string | null;
  chat_message_count: number;
};

type CalendarEventUI = {
  id: number;
  title: string;
  start_at: string;
  end_at: string;
  calendar_name: string | null;
  is_current: boolean;
  is_past: boolean;
  event_type?: string;
  event_note?: string | null;
  ai_brief?: string | null;
};

type CalendarResponse = {
  events: CalendarEventUI[];
  ai_day_insight?: string | null;
};

type Analytics = {
  total_active_minutes: number;
  productive_minutes: number;
  productive_pct: number;
  steps_today: number;
  llm_used: number;
  llm_cap: number;
  log_count: number;
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
    primary_provider?: string | null;
    fallback_providers?: string[];
    routing_mode?: string;
    available_providers?: string[];
    degraded?: boolean;
    daily_used?: number | null;
    daily_remaining?: number | null;
    daily_cap?: number | null;
    mode?: string;
  };
  build?: {
    build_version?: string;
    deployment_channel?: string;
    git_sha?: string;
  };
  database?: {
    ok?: boolean;
    error?: string;
  };
  mac?: {
    status?: string;
    reason?: string;
  };
  calendar?: {
    pending_jobs?: number;
    executor?: string;
  };
};

type CheckinResponse = {
  checkin?: string | null;
  guess?: string | null;
  event_title?: string | null;
  event_location?: string | null;
};

type HourlySummary = {
  id: number;
  hour_start_local: string;
  summary_text: string;
  productivity_score: number | null;
  source: string;
  fallback_used: boolean;
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
  is_default?: boolean;
};

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ?? "";

function apiUrl(path: string) {
  return `${API_BASE}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

function formatAge(seconds?: number) {
  if (seconds == null) return "Unknown";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

function formatTime(value?: string, timezone?: string) {
  if (!value) return "Unknown";
  const normalized = /[Z+\-]\d{2}:?\d{2}$/.test(value) ? value : value + "Z";
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(timezone ? { timeZone: timezone } : {}),
  });
}

function formatTimeOnly(value?: string, timezone?: string) {
  if (!value) return "";
  const normalized = /[Z+\-]\d{2}:?\d{2}$/.test(value) ? value : value + "Z";
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    ...(timezone ? { timeZone: timezone } : {}),
  });
}

function intervalLabel(seconds?: number) {
  if (seconds === 60) return "1 minute";
  if (seconds === 300) return "5 minutes";
  if (seconds === 900) return "15 minutes";
  if (!seconds) return "Unknown";
  return `${seconds}s`;
}

function providerLabel(provider?: string | null) {
  if (!provider) return "Unknown";
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

function stripSummaryTimePrefix(text: string): string {
  // Deterministic summaries begin with "In HH:MM AM — HH:MM AM, " — strip it since
  // the recap-time column already shows the hour.
  return text.replace(/^In \d{1,2}:\d{2}\s*[AP]M\s*[–—-]\s*\d{1,2}:\d{2}\s*[AP]M[^,]*,\s*/i, "");
}

function minutesUntil(isoStr: string): number | null {
  try {
    const diff = Math.round((new Date(isoStr).getTime() - Date.now()) / 60000);
    return diff > 0 && diff <= 90 ? diff : null;
  } catch { return null; }
}

function presenceLabel(s?: string): string {
  return ({
    active: "Active",
    idle: "Idle",
    away: "Away",
    locked: "Mac locked",
    sleeping: "Mac sleeping",
    walking: "Walking",
    at_location: "At location",
    away_from_location: "In transit",
    unknown: "Unknown",
  } as Record<string, string>)[s ?? "unknown"] ?? s ?? "Unknown";
}

function privacyLabel(value?: string) {
  return value === "detailed" ? "Detailed capture" : "Private by default";
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

function topbarLocationLabel(state: DashboardState | null) {
  if (!state?.current_location) return "Your context updates here as Vero watches the day unfold.";
  if (state.presence_display === "away_from_location") return `You just left ${state.current_location.replace(/^Outside\s+/, "")}.`;
  if (state.presence_display === "walking") return `You're moving through ${state.current_location}.`;
  return `You're at ${state.current_location}.`;
}

function productivePulseData(hourlySummaries: HourlySummary[], productivePct?: number) {
  const values = hourlySummaries
    .slice(0, 10)
    .reverse()
    .map((summary) => Math.max(12, Math.min(100, Math.round((summary.productivity_score ?? 4.5) * 10))));
  if (values.length >= 6) return values;
  const seed = Math.max(20, Math.min(96, productivePct ?? 64));
  return Array.from({ length: 8 }, (_, index) => {
    const drift = ((index % 4) - 1.5) * 10;
    return Math.max(18, Math.min(100, Math.round(seed + drift)));
  });
}

function AppShell({
  children,
  statusMessage,
  errorMessage,
  refreshing,
  onRefresh,
  state,
}: {
  children: ReactNode;
  statusMessage: string;
  errorMessage: string;
  refreshing: boolean;
  onRefresh: () => void;
  state: DashboardState | null;
}) {
  return (
    <div className="app-shell">
      <header className="topbar zen-topbar">
        <Link to="/today" className="brand-mark zen-brand-mark">
          <span className="brand-title">Vero Zen</span>
        </Link>

        <nav className="top-nav-links" aria-label="Primary navigation">
          <TopNavLink to="/today" label="Observe" />
          <TopNavLink to="/zones" label="Chronicle" />
          <TopNavLink to="/diagnostics" label="Analysis" />
          <TopNavLink to="/settings" label="Archive" />
        </nav>

        <div className="topbar-actions zen-topbar-actions">
          <button
            className="icon-button"
            onClick={onRefresh}
            type="button"
            disabled={refreshing}
            aria-label={refreshing ? "Refreshing" : "Refresh dashboard"}
            aria-busy={refreshing}
          >
            <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992V4.356" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.985 19.644v-4.992h4.992" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.93 9.348a8.25 8.25 0 0 1 13.341-3.032l2.744 2.744" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.07 14.652a8.25 8.25 0 0 1-13.341 3.032l-2.744-2.744" />
            </svg>
          </button>
          <Link className="icon-button" to="/settings" aria-label="Open settings">
            {NAV_ICONS["/settings"]}
          </Link>
        </div>
      </header>

      <aside className="side-rail" aria-label="Section shortcuts">
        <nav className="side-rail-nav">
          <NavItem to="/today" label="Observe" iconOnly />
          <NavItem to="/zones" label="Chronicle" iconOnly />
          <NavItem to="/diagnostics" label="Analysis" iconOnly />
          <NavItem to="/settings" label="Archive" iconOnly />
          <NavItem to="/setup" label="Setup" dim iconOnly />
        </nav>
      </aside>

      <div className="workspace zen-workspace">
        <main className="content zen-content">
          {statusMessage ? (
            <div className="banner success" role="status" aria-live="polite">
              {statusMessage}
            </div>
          ) : null}
          {errorMessage ? (
            <div className="banner error" role="alert" aria-live="assertive">
              {errorMessage}
            </div>
          ) : null}
          {children}
        </main>
      </div>

      <footer className="app-footer">
        <div className="app-footer-left">
          <div className="app-footer-status">
            <span className={`sidebar-status-dot bg-${serviceTone(state?.service_health)}`} />
            <span>{state?.service_health === "ok" ? "System uplink active" : state?.service_health === "offline" ? "System offline" : "System syncing"}</span>
          </div>
          <div className="app-footer-metric">Capture {intervalLabel(state?.capture_interval_seconds)}</div>
        </div>
        <div className="app-footer-right">
          <div className="app-footer-identity">
            <span>Vero Observatory</span>
            <span>{state?.current_location ?? "Awaiting place context"}</span>
          </div>
        </div>
      </footer>

      <nav className="mobile-nav">
        <NavItem to="/today" label="Observe" />
        <NavItem to="/zones" label="Chronicle" />
        <NavItem to="/diagnostics" label="Analysis" />
        <NavItem to="/settings" label="Archive" />
      </nav>
    </div>
  );
}

function TopNavLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "top-nav-link active" : "top-nav-link")}>
      {label}
    </NavLink>
  );
}

const NAV_ICONS: Record<string, ReactNode> = {
  "/today": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
    </svg>
  ),
  "/setup": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 0 1-.657.643 48.39 48.39 0 0 1-4.163-.3c.186 1.613.293 3.25.315 4.907a.656.656 0 0 1-.658.663v0c-.355 0-.676-.186-.959-.401a1.647 1.647 0 0 0-1.003-.349c-1.036 0-1.875 1.007-1.875 2.25s.84 2.25 1.875 2.25c.369 0 .713-.128 1.003-.349.283-.215.604-.401.959-.401v0c.31 0 .555.26.532.57a48.039 48.039 0 0 1-.642 5.056c1.518.19 3.058.309 4.616.354a.64.64 0 0 0 .657-.643v0c0-.355-.186-.676-.401-.959a1.647 1.647 0 0 1-.349-1.003c0-1.035 1.008-1.875 2.25-1.875 1.243 0 2.25.84 2.25 1.875 0 .369-.128.713-.349 1.003-.215.283-.401.604-.401.959v0c0 .333.277.599.61.58a48.1 48.1 0 0 0 5.427-.63 48.05 48.05 0 0 0 .582-4.717.532.532 0 0 0-.533-.57v0c-.355 0-.676.186-.959.401-.29.221-.634.349-1.003.349-1.035 0-1.875-1.007-1.875-2.25s.84-2.25 1.875-2.25c.37 0 .713.128 1.003.349.283.215.604.401.959.401v0a.656.656 0 0 0 .658-.663 48.422 48.422 0 0 0-.37-5.36c-1.886.342-3.81.574-5.766.689a.578.578 0 0 1-.61-.58v0Z" />
    </svg>
  ),
  "/diagnostics": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
    </svg>
  ),
  "/zones": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
    </svg>
  ),
  "/settings": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>
  ),
};

function NavItem({ to, label, dim, iconOnly }: { to: string; label: string; dim?: boolean; iconOnly?: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        isActive
          ? `nav-item${dim ? " nav-dim" : ""}${iconOnly ? " nav-icon-only" : ""} active`
          : `nav-item${dim ? " nav-dim" : ""}${iconOnly ? " nav-icon-only" : ""}`
      }
      aria-label={label}
    >
      {NAV_ICONS[to]}
      {!iconOnly && label}
    </NavLink>
  );
}

function StatCard({
  label,
  value,
  note,
  tone = "good",
}: {
  label: string;
  value: string;
  note: string;
  tone?: "good" | "warn" | "bad";
}) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <div className="card-label">{label}</div>
      <div className="stat-value">{value}</div>
      <p className="card-note">{note}</p>
    </article>
  );
}

function Skeleton({ h = "1em", w = "100%" }: { h?: string; w?: string }) {
  return <div className="skeleton" style={{ height: h, width: w }} />;
}

function Surface({
  title,
  eyebrow,
  children,
  action,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="surface">
      <div className="surface-header">
        <div>
          {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value: string | number | boolean | null | undefined;
}) {
  return (
    <div className="field-row">
      <span>{label}</span>
      <strong>{String(value ?? "Unknown")}</strong>
    </div>
  );
}

const QUICK_LOG_PRESETS = [
  { short: "DW", label: "Deep work", activity_type: "work" },
  { short: "ST", label: "Study", activity_type: "study" },
  { short: "RD", label: "Reading", activity_type: "reading" },
  { short: "MV", label: "Moving", activity_type: "exercise" },
  { short: "RS", label: "Rest", activity_type: "break" },
];

function TodayPage({
  state,
  analytics,
  logs,
  checkin,
  timezone,
  captureIntervalSeconds,
  initialLoading,
  onRefreshLogs,
  hourlySummaries,
  calendarEvents,
  aiDayInsight,
}: {
  state: DashboardState | null;
  analytics: Analytics | null;
  logs: ActivityLog[];
  checkin: CheckinResponse | null;
  timezone?: string;
  captureIntervalSeconds?: number;
  initialLoading: boolean;
  onRefreshLogs: () => void;
  hourlySummaries: HourlySummary[];
  calendarEvents: CalendarEventUI[];
  aiDayInsight?: string | null;
}) {
  const deferredLogs = useDeferredValue(logs);
  const [loggedMsg, setLoggedMsg] = useState("");
  const [chatMessages, setChatMessages] = useState<{user: string; reply: string; time: string}[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [checkinLoading, setCheckinLoading] = useState(false);
  const [checkinReply, setCheckinReply] = useState("");
  const [loggingActivity, setLoggingActivity] = useState<string | null>(null);

  async function handleQuickLog(activity_type: string, label: string, note?: string) {
    if (loggingActivity) return;
    setLoggingActivity(activity_type);
    try {
      await fetchJson("/api/manual-log", {
        method: "POST",
        body: JSON.stringify({ activity_type, label, note: note || undefined }),
      });
      setLoggedMsg(`${label} logged!`);
      setTimeout(() => setLoggedMsg(""), 2000);
      onRefreshLogs();
    } finally {
      setLoggingActivity(null);
    }
  }

  const handleCheckin = async (action: "confirm" | "no" | "snooze" | "dismiss") => {
    if (checkinLoading) return;
    setCheckinLoading(true);
    try {
      if (action === "confirm") {
        const reply = checkinReply.trim();
        await fetchJson("/api/checkin/confirm", {
          method: "POST",
          body: JSON.stringify(reply ? { correction: reply } : { confirmed: true }),
        }).catch(() => {});
        // Also send to chat so it's stored in history and updates context
        if (reply) {
          await fetchJson("/api/chat", {
            method: "POST",
            body: JSON.stringify({ message: reply }),
          }).catch(() => {});
        }
        setCheckinReply("");
      } else {
        const endpoint = action === "no" ? "/api/checkin/dismiss" : `/api/checkin/${action}`;
        await fetchJson(endpoint, { method: "POST" }).catch(() => {});
      }
      onRefreshLogs();
    } finally {
      setCheckinLoading(false);
    }
  };

  async function handleClearChat() {
    await fetchJson("/api/chat/history", { method: "DELETE" }).catch(() => {});
    setChatMessages([]);
  }

  useEffect(() => {
    fetchJson<{messages: {user: string; reply: string; time: string}[]}>("/api/chat/history")
      .then(r => setChatMessages(r.messages ?? []))
      .catch(() => {});
  }, []);

  async function handleChat() {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatSending(true);
    setChatInput("");
    try {
      const r = await fetchJson<{reply: string}>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: msg }),
      });
      setChatMessages(prev => [...prev, { user: msg, reply: r.reply, time: new Date().toISOString() }]);
      onRefreshLogs();
    } finally {
      setChatSending(false);
    }
  }

  const captureAgeSeconds = state?.last_mac_capture_age_seconds;
  const captureAgeMinutes = captureAgeSeconds != null ? Math.floor(captureAgeSeconds / 60) : null;
  const pulseValues = productivePulseData(hourlySummaries, analytics?.productive_pct);
  const currentFocus = state?.current_activity_summary ?? "Waiting for your first capture";
  const currentCategory = state?.current_activity_category?.replace(/_/g, " ") ?? "unknown";
  const systemTitle = logs[0]?.app_name || state?.current_activity_category || "Idle";
  const systemDetail = logs[0]?.window_title || state?.current_activity_summary || "No active window detail yet";
  const chronicleEntries = [
    aiDayInsight,
    ...hourlySummaries.slice(0, 2).map((summary) => stripSummaryTimePrefix(summary.summary_text)),
    state?.current_event_title ? `Current calendar anchor: ${state.current_event_title}.` : null,
  ].filter((entry): entry is string => Boolean(entry && entry.trim()));

  return (
    <div className="zen-observe-page">
      <div className="zen-editorial-layout">
        <div className="zen-main-column">
          <section className="zen-hero">
            <p className="zen-greeting">{timeGreeting()}</p>
            <h2 className="zen-hero-title">
              What is the focus for the next hour?
              <span>{initialLoading ? "Reading the room..." : currentFocus}</span>
            </h2>

            <div className="zen-mode-row">
              {QUICK_LOG_PRESETS.map(({ short, label, activity_type }, index) => (
                <button
                  key={activity_type}
                  className={index === 0 ? "zen-mode-button active" : "zen-mode-button"}
                  onClick={() => void handleQuickLog(activity_type, label)}
                  disabled={!!loggingActivity}
                >
                  <span>{label}</span>
                  <span className="zen-mode-code">{loggingActivity === activity_type ? ".." : short}</span>
                </button>
              ))}
            </div>

            <div className="zen-intent-entry">
              <input
                className="zen-intent-input"
                placeholder="Write the next move..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !chatSending) void handleChat(); }}
              />
              <button className="zen-intent-submit" type="button" onClick={() => void handleChat()} disabled={!chatInput.trim() || chatSending}>
                {chatSending ? "Sending" : "Log intent"}
              </button>
            </div>

            {loggedMsg && <div className="quicklog-confirm">{loggedMsg}</div>}
          </section>

          <section className="zen-data-row">
            <article className="zen-data-block">
              <p className="zen-section-label">Environmental status</p>
              <div>
                <p className="zen-primary-reading">{state?.current_location ?? "Unknown location"}</p>
                <p className="zen-secondary-reading">
                  {presenceLabel(state?.presence_display ?? state?.presence_state)}
                  {captureAgeMinutes != null ? ` · ${captureAgeMinutes}m since capture` : " · Waiting for capture"}
                </p>
                <p className="zen-micro-link">{systemDetail}</p>
              </div>
            </article>

            <article className="zen-data-block">
              <p className="zen-section-label">Performance metrics</p>
              <div className="zen-metric-grid">
                <div>
                  <p className="zen-metric-value">{analytics?.productive_minutes ?? 0}m</p>
                  <p className="zen-metric-label">Productive</p>
                </div>
                <div>
                  <p className="zen-metric-value">{analytics?.productive_pct ?? 0}%</p>
                  <p className="zen-metric-label">Focus</p>
                </div>
              </div>
              <div className="pulse-chart zen-pulse-chart" aria-hidden="true">
                {pulseValues.map((value, index) => (
                  <span key={`${value}-${index}`} className="pulse-bar" style={{ height: `${value}%` }} />
                ))}
              </div>
            </article>
          </section>

          {checkin?.checkin ? (
            <Surface title="Check-in" eyebrow="Needs input">
              {checkin.event_title ? (
                <p className="cal-brief">{checkin.event_title}{checkin.event_location ? ` · ${checkin.event_location}` : ""}</p>
              ) : null}
              <p className="lead">{checkin.checkin}</p>
              <div className="quicklog-custom" style={{ marginTop: "10px" }}>
                <input
                  className="quicklog-input"
                  placeholder={checkin.guess ? `Confirm \"${checkin.guess}\" or type something else...` : "What are you working on?"}
                  value={checkinReply}
                  disabled={checkinLoading}
                  autoFocus
                  onChange={e => setCheckinReply(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !checkinLoading && (checkinReply.trim() || checkin.guess)) void handleCheckin("confirm"); }}
                />
                <button
                  className="primary-button"
                  disabled={checkinLoading || (!checkinReply.trim() && !checkin.guess)}
                  onClick={() => void handleCheckin("confirm")}
                >
                  {checkinLoading ? "Sending..." : "Send"}
                </button>
              </div>
              <div className="checkin-actions">
                <button className="secondary-button" disabled={checkinLoading} onClick={() => void handleCheckin("snooze")}>Remind later</button>
                <button className="secondary-button ghost-button" disabled={checkinLoading} onClick={() => void handleCheckin("dismiss")}>Dismiss</button>
              </div>
            </Surface>
          ) : null}

          {calendarEvents.length > 0 && (
            <Surface title="Current field" eyebrow="Calendar">
              <div className="cal-strip">
                {calendarEvents.map((ev) => {
                  const minsAway = minutesUntil(ev.start_at);
                  return (
                    <div key={ev.id} className={`cal-event cal-type-${ev.event_type ?? "other"}${ev.is_current ? " cal-current" : ev.is_past ? " cal-past" : ""}`}>
                      <span className="cal-time">{formatTimeOnly(ev.start_at, timezone)}</span>
                      <span className="cal-title-group">
                        <span className="cal-title">{ev.event_type === "assignment" ? `Due: ${ev.title}` : ev.title}</span>
                        {ev.event_note && <span className="cal-note">{ev.event_note}</span>}
                      </span>
                      {ev.event_type && ev.event_type !== "other" && (
                        <span className={`cal-type-badge cal-type-badge-${ev.event_type}`}>{ev.event_type.replace("_", " ")}</span>
                      )}
                      {ev.calendar_name && <span className="cal-name">{ev.calendar_name}</span>}
                      {ev.is_current && <span className="cal-badge">Now</span>}
                      {minsAway != null && minsAway <= 30 ? <span className="cal-countdown">in {minsAway}m</span> : null}
                      {ev.ai_brief && <span className="cal-brief">{ev.ai_brief}</span>}
                    </div>
                  );
                })}
              </div>
            </Surface>
          )}

          <Surface title="Live feed" eyebrow="Recent activity">
            <div className="timeline tactical-timeline">
              {initialLoading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <article className="timeline-row" key={i}>
                    <div className="timeline-time"><Skeleton h="0.9rem" w="90px" /></div>
                    <div className="timeline-copy"><Skeleton h="0.9rem" w="100%" /></div>
                    <div className="timeline-meta"><Skeleton h="0.9rem" w="60px" /></div>
                  </article>
                ))
              ) : deferredLogs.length ? (
                deferredLogs.map((entry) => (
                  <article className="timeline-row" key={entry.id}>
                    <div className="timeline-time">{formatTime(entry.timestamp, timezone)}</div>
                    <div className="timeline-copy">
                      <strong>{entry.app_name || entry.location_label || entry.activity_type || "Activity"}</strong>
                      <p>{entry.window_title || entry.activity_type || entry.location_label || "No detail available"}</p>
                    </div>
                    <div className="timeline-meta">
                      {entry.device === "manual"
                        ? <span className="tag tag-manual">manual</span>
                        : entry.activity_type && entry.activity_type !== "unknown"
                          ? <span className="tag">{entry.activity_type}</span>
                          : presenceLabel(entry.presence_state)}
                    </div>
                  </article>
                ))
              ) : (
                <div className="empty-cta">
                  <p className="empty-cta-heading">No captures yet</p>
                  <p className="muted">Once the Mac companion is running, activity appears here automatically.</p>
                  <Link className="secondary-link" to="/setup">Go to Setup →</Link>
                </div>
              )}
            </div>
          </Surface>
        </div>

        <aside className="zen-chronicle-column">
          <section className="zen-chronicle-panel">
            <p className="zen-section-label zen-chronicle-label">Session Chronicle</p>
            <div className="zen-chronicle-list">
              {(chronicleEntries.length ? chronicleEntries : [
                `${systemTitle} remains the main focus in the current session.`,
                `${currentCategory.charAt(0).toUpperCase()}${currentCategory.slice(1)} is the strongest category signal right now.`,
                `${state?.current_location ?? "Current context"} looks stable enough for continuation.`,
              ]).map((entry, index) => (
                <article key={`${index}-${entry.slice(0, 16)}`} className="zen-chronicle-entry">
                  <p>{entry}</p>
                </article>
              ))}
            </div>

            <div className="zen-kernel-grid">
              <div className="zen-kernel-row">
                <span>Kernel status</span>
                <span>{state?.service_health === "ok" ? "Active" : "Recovering"}</span>
              </div>
              <div className="zen-kernel-row">
                <span>Neural sync</span>
                <span>{analytics?.productive_pct ?? 0}%</span>
              </div>
              <div className="zen-kernel-row">
                <span>Observed app</span>
                <span>{systemTitle}</span>
              </div>
            </div>
          </section>

          <Surface
            title="Intent dialogue"
            eyebrow="Conversation"
            action={chatMessages.length > 0 ? (
              <button className="secondary-button compact-button" onClick={() => void handleClearChat()}>Clear</button>
            ) : undefined}
          >
            {chatMessages.length > 0 ? (
              <div className="chat-history">
                {chatMessages.map((m, i) => (
                  <div key={i} className="chat-pair">
                    <div className="chat-user">{m.user}</div>
                    <div className="chat-reply">{m.reply}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No active thread yet. Use the focus prompt to tell Vero what you are doing or where you are.</p>
            )}
          </Surface>

          {hourlySummaries.length > 0 && (
            <Surface title="AI recap" eyebrow="Recent passages">
              <div className="recap-list">
                {hourlySummaries.map(s => (
                  <div key={s.id} className="recap-row">
                    <span className="recap-time">{formatTime(s.hour_start_local, timezone)}</span>
                    <div className="recap-body">
                      <span className="recap-text">{stripSummaryTimePrefix(s.summary_text)}</span>
                      {s.productivity_score != null && (
                        <div className="recap-score-bar">
                          <div
                            className="recap-score-fill"
                            style={{ width: `${s.productivity_score * 10}%`, '--score': s.productivity_score } as React.CSSProperties}
                          />
                          <span className="recap-score-label">{s.productivity_score.toFixed(1)}</span>
                        </div>
                      )}
                    </div>
                    <div className="recap-right">
                      {s.source === "llm" && !s.fallback_used
                        ? <span className="recap-badge recap-badge-ai">AI</span>
                        : <span className="recap-badge recap-badge-est">est.</span>}
                    </div>
                  </div>
                ))}
              </div>
            </Surface>
          )}
        </aside>
      </div>
    </div>
  );
}

function SetupPage({
  state,
  health,
}: {
  state: DashboardState | null;
  health: HealthResponse | null;
}) {
  const heartbeatReady = (state?.last_mac_heartbeat_age_seconds ?? Number.MAX_SAFE_INTEGER) < 3600;
  const captureReady = (state?.last_mac_capture_age_seconds ?? Number.MAX_SAFE_INTEGER) < 3600;
  const backendUrl = state?.backend_target_url ?? window.location.origin;

  return (
    <div className="stack">
      <Surface title="Setup" eyebrow="Onboarding checklist">
        <div className="step-grid">
          <SetupStep
            title="1. Launch the menu bar companion"
            status={heartbeatReady ? "Done" : "Waiting"}
            body="Open Vero on Mac, paste your backend URL and password, then keep it running from the menu bar."
          />
          <SetupStep
            title="2. Confirm first heartbeat"
            status={heartbeatReady ? "Done" : "Waiting"}
            body={`Latest heartbeat: ${formatAge(state?.last_mac_heartbeat_age_seconds)}`}
          />
          <SetupStep
            title="3. Confirm first capture"
            status={captureReady ? "Done" : "Waiting"}
            body={`Latest capture: ${formatAge(state?.last_mac_capture_age_seconds)}`}
          />
          <SetupStep
            title="4. Add optional iPhone shortcuts"
            status={state?.ios_recent_event ? "Active" : state?.ios_ever_setup ? "Done" : "Optional"}
            body="Download the shortcuts below and install them on iPhone for zone and sleep context."
          />
        </div>
      </Surface>

      <Surface title="Mac companion" eyebrow="Menu bar app">
        <div className="field-row">
          <span>Backend URL</span>
          <strong style={{ wordBreak: "break-all", textAlign: "right" }}>{backendUrl}</strong>
        </div>
        <div className="field-row">
          <span>Backend health</span>
          <strong className={`tone-${serviceTone(health?.status)}`}>{health?.status ?? "unknown"}</strong>
        </div>
        <div className="field-row">
          <span>Last heartbeat</span>
          <strong>{formatAge(state?.last_mac_heartbeat_age_seconds)}</strong>
        </div>
        <p className="muted" style={{ marginTop: "14px" }}>
          Enter the backend URL and your password in the Vero Mac app. Once connected, keep it
          running in the menu bar — it stays out of the way after the first setup.
          Relaunch only to reconnect or fix Accessibility / Screen Recording permissions.
        </p>
      </Surface>

      <Surface title="iPhone shortcuts" eyebrow="Optional companion context">
        <p className="lead">
          These shortcuts send zone and activity signals to the backend. Tap each link on your iPhone
          (or AirDrop the file) to install.
        </p>
        <div className="step-grid" style={{ marginTop: "16px" }}>
          <ShortcutCard
            name="Vero Walking"
            description="Triggers when you start a walking workout in Apple Health."
            downloadUrl={`${backendUrl}/setup/shortcut/download?kind=walking`}
          />
          <ShortcutCard
            name="Vero Charging On"
            description="Signals when your iPhone starts charging — useful as a sleep proxy."
            downloadUrl={`${backendUrl}/setup/shortcut/download?kind=charge_on`}
          />
          <ShortcutCard
            name="Vero Charging Off"
            description="Signals when your iPhone stops charging — wakeup proxy."
            downloadUrl={`${backendUrl}/setup/shortcut/download?kind=charge_off`}
          />
        </div>
        <p className="muted" style={{ marginTop: "14px" }}>
          After downloading, tap <strong>Add Shortcut</strong> in the iOS Shortcuts app and run it
          once to grant location permission if prompted. Zones and sleep signals are optional —
          Vero works without them.
        </p>
      </Surface>
    </div>
  );
}

function ShortcutCard({
  name,
  description,
  downloadUrl,
}: {
  name: string;
  description: string;
  downloadUrl: string;
}) {
  return (
    <article className="step-card">
      <div className="step-topline">
        <h3>{name}</h3>
        <a className="secondary-link" href={downloadUrl} download>
          Download
        </a>
      </div>
      <p className="muted">{description}</p>
    </article>
  );
}

function SetupStep({
  title,
  status,
  body,
}: {
  title: string;
  status: string;
  body: string;
}) {
  return (
    <article className="step-card">
      <div className="step-topline">
        <h3>{title}</h3>
        <span className={`pill tone-${status === "Done" || status === "Active" ? "good" : "warn"}`}>
          {status}
        </span>
      </div>
      <p className="muted">{body}</p>
    </article>
  );
}

function DiagnosticsPage({
  state,
  health,
  settings,
}: {
  state: DashboardState | null;
  health: HealthResponse | null;
  settings: BackendSettings | null;
}) {
  const [contextSummary, setContextSummary] = useState<ContextSummary | null>(null);
  const [rawState, setRawState] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    fetchJson<ContextSummary>("/api/context-summary").then(setContextSummary).catch(() => {});
    fetchJson<Record<string, unknown>>("/api/state").then(setRawState).catch(() => {});
  }, []);

  const handleClearContext = async () => {
    await fetchJson("/api/chat/history", { method: "DELETE" }).catch(() => {});
    setContextSummary(prev => prev ? { ...prev, facts: [], chat_message_count: 0, current_self_report: "" } : null);
  };

  return (
    <div className="page-grid">
      <div className="stack">
        <Surface title="Agent diagnostics" eyebrow="Health & recency">
          <Field label="Service health" value={health?.status ?? "Unknown"} />
          <Field label="Mac status" value={state?.mac_status_reason ?? "Unknown"} />
          <Field label="Presence" value={presenceLabel(state?.presence_state)} />
          <Field label="Screen state" value={state?.screen_state ?? "Unknown"} />
          <Field label="Last heartbeat" value={formatAge(state?.last_mac_heartbeat_age_seconds)} />
          <Field label="Last capture" value={formatAge(state?.last_mac_capture_age_seconds)} />
          <Field label="Last presence change" value={formatTime(state?.last_presence_change_at)} />
        </Surface>

        <Surface title="AI & Intelligence" eyebrow="LLM status">
          <Field label="Can use AI" value={health?.llm?.configured ? "Yes" : "No"} />
          <Field label="Effective provider" value={providerLabel(health?.llm?.provider)} />
          <Field label="Primary provider" value={providerLabel(settings?.ai_primary_provider ?? settings?.ai_provider)} />
          <Field label="Fallbacks" value={(settings?.ai_fallback_providers ?? []).map(providerLabel).join(", ") || "None"} />
          <Field label="Routing mode" value={health?.llm?.routing_mode ?? settings?.ai_routing_mode ?? "Unknown"} />
          <Field label="AI mode" value={settings?.llm_mode ?? "Unknown"} />
          <Field label="Hourly summaries" value={settings?.hourly_summaries_enabled ? "Enabled" : "Disabled"} />
        </Surface>

        <Surface title="Recovery actions" eyebrow="When something looks wrong">
          <ul className="plain-list">
            <li>If heartbeat is fresh but capture is stale, check dashboard settings first and confirm tracking is still enabled.</li>
            <li>If both heartbeat and capture are stale, relaunch Vero from Applications or reopen the Mac setup guide to reconnect the menu bar companion.</li>
            <li>If status is degraded, finish Accessibility, Notifications, or Calendar permissions on macOS.</li>
          </ul>
        </Surface>
      </div>

      <div className="stack">
        <Surface title="Backend details" eyebrow="Build">
          <Field label="Version" value={health?.build?.build_version ?? "Unknown"} />
          <Field label="Git SHA" value={health?.build?.git_sha ?? "Unknown"} />
          <Field label="Database" value={health?.database?.ok ? "Healthy" : health?.database?.error ?? "Unknown"} />
          <Field label="Uptime" value={health?.uptime_seconds ? `${Math.floor(health.uptime_seconds / 60)} min` : "Unknown"} />
        </Surface>

        <Surface title="Current settings" eyebrow="Dashboard source of truth">
          <Field label="Capture interval" value={intervalLabel(settings?.capture_interval_seconds)} />
          <Field label="Privacy mode" value={privacyLabel(settings?.privacy_mode)} />
          <Field label="Calendar sync" value={settings?.calendar_sync_enabled ? "Enabled" : "Disabled"} />
          <Field label="Tracking" value={settings?.tracking_enabled ? "Enabled" : "Paused"} />
        </Surface>

        {health?.startup_errors && health.startup_errors.length > 0 && (
          <Surface title="Errors & Pending Work" eyebrow="Needs attention">
            {health.startup_errors.map((err, i) => (
              <div key={i} className="muted" style={{ fontSize: "0.85rem", marginBottom: "4px" }}>⚠ {err}</div>
            ))}
            {health.calendar?.pending_jobs != null && (
              <Field label="Pending calendar jobs" value={health.calendar.pending_jobs} />
            )}
          </Surface>
        )}

        <Surface
          title="What Vero knows"
          eyebrow="Context state"
          action={
            <button className="secondary-button" style={{ fontSize: "0.8rem", padding: "4px 10px", color: "var(--bad)" }} onClick={() => void handleClearContext()}>
              Clear all
            </button>
          }
        >
          {contextSummary ? (
            <>
              <Field label="Location" value={contextSummary.current_location || "Unknown"} />
              <Field label="Activity" value={contextSummary.activity_category || "Unknown"} />
              <Field label="Self-report" value={contextSummary.current_self_report || "None"} />
              <Field label="Zone lock" value={contextSummary.zone_lock_active ? `Until ${contextSummary.zone_lock_until ?? "?"}` : "None"} />
              <Field label="Chat messages" value={contextSummary.chat_message_count} />
              {contextSummary.facts.length > 0 && (
                <div style={{ marginTop: "12px" }}>
                  <div className="eyebrow" style={{ marginBottom: "6px" }}>Remembered facts ({contextSummary.facts.length})</div>
                  <ul className="plain-list" style={{ fontSize: "0.85rem" }}>
                    {contextSummary.facts.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <span className="muted">Loading…</span>
          )}
        </Surface>

        <details style={{ marginTop: "8px" }}>
          <summary style={{ cursor: "pointer", color: "var(--muted)", fontSize: "0.85rem" }}>Raw state (debug)</summary>
          <pre style={{ fontSize: "0.75rem", overflowX: "auto", maxHeight: "400px", marginTop: "8px", padding: "12px", background: "var(--panel)", borderRadius: "8px" }}>
            {rawState ? JSON.stringify(rawState, null, 2) : "Loading…"}
          </pre>
        </details>
      </div>
    </div>
  );
}

function ZonesPage({
  initialZones,
  onReload,
  setStatusMessage,
  setErrorMessage,
}: {
  initialZones: ZoneRecord[];
  onReload: () => Promise<void>;
  setStatusMessage: (message: string) => void;
  setErrorMessage: (message: string) => void;
}) {
  const [zones, setZones] = useState<ZoneRecord[]>(initialZones);
  const [newZone, setNewZone] = useState<ZoneRecord>({
    slug: "",
    name: "",
    radius_meters: 75,
    enabled: true,
    zone_type: "custom",
    focus_mode: "",
    sort_order: 0,
  });

  useEffect(() => {
    startTransition(() => setZones(initialZones));
  }, [initialZones]);

  async function saveZone(zone: ZoneRecord) {
    setErrorMessage("");
    try {
      const path = zone.id ? `/api/zones/${zone.id}` : "/api/zones";
      const method = zone.id ? "PATCH" : "POST";
      await fetchJson(path, {
        method,
        body: JSON.stringify(zone),
      });
      setStatusMessage(zone.id ? "Zone updated." : "Zone created.");
      if (!zone.id) {
        setNewZone({
          slug: "",
          name: "",
          radius_meters: 75,
          enabled: true,
          zone_type: "custom",
          focus_mode: "",
          sort_order: 0,
        });
      }
      await onReload();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to save zone.");
    }
  }

  async function removeZone(zone: ZoneRecord) {
    if (!zone.id) return;
    setErrorMessage("");
    try {
      await fetchJson(`/api/zones/${zone.id}`, { method: "DELETE" });
      setStatusMessage("Zone deleted.");
      await onReload();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to delete zone.");
    }
  }

  return (
    <div className="stack">
      <Surface
        title="Zones"
        eyebrow="Location intelligence"
        action={
          <Link className="secondary-link" to="/setup">
            iPhone setup →
          </Link>
        }
      >
        <p className="muted">
          Zones let Vero know where you are using iPhone GPS automations. Mark one zone as <strong>Home</strong> so commutes and sleep detection work correctly. GPS isn't always precise — you can also just tell Vero where you are via the chat or quick-log on the Today page.
        </p>
      </Surface>

      <Surface title="Existing zones" eyebrow="Create, edit, delete">
        <div className="zone-grid">
          {zones.map((zone) => (
            <ZoneEditor
              key={zone.id ?? zone.slug}
              zone={zone}
              onSave={saveZone}
              onDelete={removeZone}
            />
          ))}
          {!zones.length ? <p className="empty-state">No zones configured yet.</p> : null}
        </div>
      </Surface>

      <Surface title="Add zone" eyebrow="Quick create">
        <ZoneForm zone={newZone} onChange={setNewZone} />
        <div className="surface-actions">
          <button
            className="primary-button"
            type="button"
            onClick={() =>
              saveZone({
                ...newZone,
                slug: slugify(newZone.slug || newZone.name),
              })
            }
          >
            Create zone
          </button>
        </div>
      </Surface>
    </div>
  );
}

function ZoneEditor({
  zone,
  onSave,
  onDelete,
}: {
  zone: ZoneRecord;
  onSave: (zone: ZoneRecord) => Promise<void>;
  onDelete: (zone: ZoneRecord) => Promise<void>;
}) {
  const [draft, setDraft] = useState(zone);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(zone);
  }, [zone]);

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(draft); } finally { setSaving(false); }
  };
  const handleDelete = async () => {
    setSaving(true);
    try { await onDelete(draft); } finally { setSaving(false); }
  };

  const zoneTypeInfo = ZONE_TYPES.find(t => t.value === zone.zone_type);
  return (
    <article className="zone-card">
      <div className="zone-card-header">
        <div className="zone-card-title">
          <span className="zone-type-icon">{zoneTypeInfo?.label.split(" ")[0] ?? "📍"}</span>
          <strong>{zone.name || "Unnamed zone"}</strong>
          {zone.zone_type === "home" && <span className="zone-home-badge">Home</span>}
        </div>
        <span className="zone-radius-hint">{zone.radius_meters}m radius</span>
      </div>
      <ZoneForm zone={draft} onChange={setDraft} />
      <div className="surface-actions">
        <button className="secondary-button" type="button" disabled={saving} onClick={() => void handleSave()}>
          {saving ? "…" : "Save"}
        </button>
        <button className="danger-button" type="button" disabled={saving} onClick={() => void handleDelete()}>
          Delete
        </button>
      </div>
    </article>
  );
}

const ZONE_TYPES = [
  { value: "home",    label: "🏠 Home" },
  { value: "campus",  label: "🎓 Campus / School" },
  { value: "work",    label: "💼 Work / Office" },
  { value: "gym",     label: "🏋️ Gym" },
  { value: "cafe",    label: "☕ Café" },
  { value: "custom",  label: "📍 Other" },
];

function ZoneForm({
  zone,
  onChange,
}: {
  zone: ZoneRecord;
  onChange: (zone: ZoneRecord) => void;
}) {
  return (
    <div className="form-grid">
      <label className="field">
        <span>Name</span>
        <input
          value={zone.name}
          onChange={(event) => onChange({ ...zone, name: event.target.value })}
          placeholder="e.g. Anchor Café"
        />
      </label>
      <label className="field">
        <span>Type</span>
        <select
          value={zone.zone_type}
          onChange={(event) => onChange({ ...zone, zone_type: event.target.value })}
        >
          {ZONE_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Slug</span>
        <input
          value={zone.slug}
          onChange={(event) => onChange({ ...zone, slug: slugify(event.target.value) })}
          placeholder="anchor-cafe"
        />
      </label>
      <label className="field">
        <span>GPS radius (m)</span>
        <input
          type="number"
          min={20}
          max={500}
          value={zone.radius_meters}
          onChange={(event) => onChange({ ...zone, radius_meters: Number(event.target.value) })}
        />
      </label>
      <label className="field">
        <span>iOS Focus mode</span>
        <input
          value={zone.focus_mode}
          onChange={(event) => onChange({ ...zone, focus_mode: event.target.value })}
          placeholder="e.g. Do Not Disturb"
        />
      </label>
    </div>
  );
}

function CalendarSettingsPanel({
  settings,
  onSave,
}: {
  settings: BackendSettings;
  onSave: (s: BackendSettings) => Promise<void>;
}) {
  const initialUrls = settings.calendar_ical_urls?.length
    ? settings.calendar_ical_urls
    : settings.calendar_ical_url
    ? [settings.calendar_ical_url]
    : [""];
  const [urls, setUrls] = useState<string[]>(initialUrls);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  const lastSync = settings.calendar_last_sync
    ? formatAge(Math.floor((Date.now() - new Date(settings.calendar_last_sync).getTime()) / 1000))
    : null;

  function updateUrl(index: number, value: string) {
    const next = [...urls];
    next[index] = value;
    setUrls(next);
  }

  function removeUrl(index: number) {
    setUrls(urls.filter((_, i) => i !== index));
  }

  function addUrl() {
    setUrls([...urls, ""]);
  }

  async function handleSave() {
    const cleaned = urls.filter(u => u.trim());
    await onSave({ ...settings, calendar_ical_urls: cleaned, calendar_ical_url: cleaned[0] ?? "" });
  }

  async function handleSyncNow() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const res = await fetchJson<{ synced: number; error: string }>("/api/calendar/sync-now", { method: "POST" });
      setSyncMsg(res.error ? `Error: ${res.error}` : `Synced ${res.synced} events`);
    } catch {
      setSyncMsg("Sync failed");
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(""), 4000);
    }
  }

  const hasAnyUrl = urls.some(u => u.trim());

  return (
    <Surface
      title="Calendar"
      eyebrow="iCal sync"
      action={
        <button className="secondary-button" type="button" onClick={handleSyncNow} disabled={syncing || !hasAnyUrl}>
          {syncing ? "Syncing…" : "Sync now"}
        </button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {urls.map((url, i) => (
          <div key={i} style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <input
              type="url"
              value={url}
              placeholder="webcal:// or https://..."
              onChange={(e) => updateUrl(i, e.target.value)}
              style={{ fontFamily: "monospace", fontSize: "0.82rem", flex: 1 }}
            />
            {urls.length > 1 && (
              <button
                type="button"
                onClick={() => removeUrl(i)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: "1rem" }}
                aria-label="Remove"
              >✕</button>
            )}
          </div>
        ))}
        <button type="button" className="secondary-button" onClick={addUrl} style={{ alignSelf: "flex-start", fontSize: "0.82rem" }}>
          + Add calendar
        </button>
      </div>
      <p className="field-hint" style={{ marginTop: "8px" }}>
        Google Calendar: calendar settings → "Secret address in iCal format". iCloud: share calendar → copy link. Vero syncs every 30 min.
      </p>
      {settings.calendar_sync_error && (
        <p className="field-hint" style={{ color: "var(--bad)", marginTop: "8px" }}>
          Last sync error: {settings.calendar_sync_error}
        </p>
      )}
      {!settings.calendar_sync_error && lastSync && (
        <p className="field-hint" style={{ marginTop: "8px" }}>Last synced {lastSync}</p>
      )}
      {syncMsg && <p className="field-hint" style={{ color: syncMsg.startsWith("Error") ? "var(--bad)" : "var(--good)", marginTop: "8px" }}>{syncMsg}</p>}
      <div className="surface-actions">
        <button className="primary-button" type="button" onClick={handleSave}>Save</button>
      </div>
    </Surface>
  );
}


function SettingsPage({
  settings,
  onSave,
}: {
  settings: BackendSettings | null;
  onSave: (settings: BackendSettings) => Promise<void>;
}) {
  const [draft, setDraft] = useState<BackendSettings | null>(settings);
  const [saving, setSaving] = useState(false);

  function normalizeSettings(next: BackendSettings | null) {
    if (!next) return next;
    return {
      ...next,
      ai_primary_provider: next.ai_primary_provider ?? next.ai_provider,
      ai_fallback_providers: next.ai_fallback_providers ?? ["gemini", "openai"],
      ai_routing_mode: next.ai_routing_mode ?? "task_aware",
    };
  }

  useEffect(() => {
    setDraft(normalizeSettings(settings));
  }, [settings]);

  if (!draft) {
    return <Surface title="Settings">Loading settings…</Surface>;
  }

  const handleSaveSettings = async () => {
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="stack">
      <Surface
        title="Settings"
        eyebrow="Tracking & privacy"
        action={
          <button className="primary-button" type="button" disabled={saving} onClick={() => void handleSaveSettings()}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        }
      >
        <div className="form-grid">
          <label className="toggle-field">
            <span>Tracking enabled</span>
            <input
              type="checkbox"
              checked={draft.tracking_enabled}
              onChange={(event) =>
                setDraft({ ...draft, tracking_enabled: event.target.checked })
              }
            />
          </label>
          <p className="field-hint">Pause all data collection</p>

          <label className="field">
            <span>Capture interval</span>
            <select
              value={draft.capture_interval_seconds}
              onChange={(event) => {
                const value = Number(event.target.value);
                setDraft({
                  ...draft,
                  capture_interval_seconds: value,
                  polling_interval_seconds: value,
                  classification_interval_seconds: Math.max(300, value),
                });
              }}
            >
              <option value={60}>1 minute</option>
              <option value={300}>5 minutes</option>
              <option value={900}>15 minutes — least battery impact</option>
            </select>
          </label>
          <p className="field-hint">How often the Mac agent records a snapshot</p>

          <label className="field">
            <span>Capture detail</span>
            <select
              value={draft.privacy_mode}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  privacy_mode: event.target.value as BackendSettings["privacy_mode"],
                })
              }
            >
              <option value="detailed">Full — app names + window titles (recommended)</option>
              <option value="private">Minimal — app names only</option>
            </select>
          </label>
          <p className="field-hint">Full capture enables window-level timeline detail and better AI summaries</p>

          <label className="field">
            <span>Timezone</span>
            <select
              value={draft.user_timezone}
              onChange={(event) => setDraft({ ...draft, user_timezone: event.target.value })}
            >
              {timezoneOptions(draft.user_timezone).map((timezone) => (
                <option key={timezone} value={timezone}>
                  {timezone}
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">Used to display times correctly</p>
        </div>
      </Surface>

      <Surface title="AI" eyebrow="Intelligence">
        <div className="form-grid">
          <label className="field">
            <span>Primary provider</span>
            <select
              value={draft.ai_provider}
              onChange={(event) => setDraft({ ...draft, ai_provider: event.target.value, ai_primary_provider: event.target.value })}
            >
              <option value="mistral">Mistral — recommended</option>
              <option value="auto">Auto</option>
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          <p className="field-hint">Mistral is the default path. Interactive requests can fall back when enabled.</p>

          <label className="field">
            <span>Fallback providers</span>
            <select
              multiple
              value={draft.ai_fallback_providers}
              onChange={(event) => {
                const values = Array.from(event.target.selectedOptions, (option) => option.value);
                setDraft({ ...draft, ai_fallback_providers: values.filter((value) => value !== draft.ai_provider) });
              }}
            >
              {["mistral", "gemini", "openai"].map((provider) => (
                <option key={provider} value={provider} disabled={provider === draft.ai_provider}>
                  {providerLabel(provider)}
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">Hold Command to select more than one fallback provider.</p>

          <label className="field">
            <span>Routing behavior</span>
            <select
              value={draft.ai_routing_mode}
              onChange={(event) => setDraft({ ...draft, ai_routing_mode: event.target.value })}
            >
              <option value="task_aware">Task-aware fallback</option>
              <option value="aggressive_fallback">Always fall back</option>
              <option value="strict_primary">Strict primary only</option>
            </select>
          </label>
          <p className="field-hint">Task-aware keeps Mistral primary and spends fallback providers mostly on interactive requests.</p>

          <label className="toggle-field">
            <span>Hourly summaries</span>
            <input
              type="checkbox"
              checked={draft.hourly_summaries_enabled}
              onChange={e => setDraft({ ...draft, hourly_summaries_enabled: e.target.checked })}
            />
          </label>
          <p className="field-hint">AI generates a recap and productivity score each hour</p>
        </div>
      </Surface>

      <CalendarSettingsPanel settings={draft} onSave={onSave} />
    </div>
  );
}

function timezoneOptions(current: string) {
  const options = [
    "America/Los_Angeles",
    "America/New_York",
    "Europe/London",
    "Europe/Paris",
    "Asia/Tokyo",
    "UTC",
  ];
  return options.includes(current) ? options : [current, ...options];
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function App() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [settings, setSettings] = useState<BackendSettings | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [checkin, setCheckin] = useState<CheckinResponse | null>(null);
  const [zones, setZones] = useState<ZoneRecord[]>([]);
  const [hourlySummaries, setHourlySummaries] = useState<HourlySummary[]>([]);
  const [calendarEvents, setCalendarEvents] = useState<CalendarEventUI[]>([]);
  const [aiDayInsight, setAiDayInsight] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [isOffline, setIsOffline] = useState(false);

  // Full initial load — all 6 endpoints in parallel
  async function refreshCore() {
    setRefreshing(true);
    setErrorMessage("");
    try {
      const [stateResult, settingsResult, analyticsResult, logsResult, healthResult, checkinResult] =
        await Promise.allSettled([
          fetchJson<DashboardState>("/api/state"),
          fetchJson<BackendSettings>("/api/settings"),
          fetchJson<Analytics>("/api/analytics/today"),
          fetchJson<ActivityLog[]>("/api/logs?limit=15"),
          fetchJson<HealthResponse>("/api/healthz"),
          fetchJson<CheckinResponse>("/api/checkin"),
        ]);

      if (stateResult.status !== "fulfilled" || settingsResult.status !== "fulfilled") {
        throw new Error("Core backend endpoints are unavailable.");
      }

      startTransition(() => {
        setState(stateResult.value);
        setSettings(settingsResult.value);
        if (analyticsResult.status === "fulfilled") setAnalytics(analyticsResult.value);
        if (logsResult.status === "fulfilled") setLogs(logsResult.value);
        if (healthResult.status === "fulfilled") setHealth(healthResult.value);
        if (checkinResult.status === "fulfilled") setCheckin(checkinResult.value);
        setInitialLoading(false);
        setIsOffline(false);
      });
    } catch (error) {
      if (initialLoading) {
        setIsOffline(true);
      }
      setErrorMessage(error instanceof Error ? error.message : "Failed to refresh data.");
      setInitialLoading(false);
    } finally {
      setRefreshing(false);
    }
  }

  // Tight loop (60s) — only the two live-changing endpoints
  async function refreshLive() {
    try {
      const [nextState, nextLogs] = await Promise.all([
        fetchJson<DashboardState>("/api/state"),
        fetchJson<ActivityLog[]>("/api/logs?limit=15"),
      ]);
      startTransition(() => {
        setState(nextState);
        setLogs(nextLogs);
      });
    } catch { /* silent — errors shown on next full refresh */ }
  }

  // Medium loop (2 min) — analytics + checkin change on new captures
  async function refreshAnalytics() {
    try {
      const [nextAnalytics, nextCheckin] = await Promise.all([
        fetchJson<Analytics>("/api/analytics/today"),
        fetchJson<CheckinResponse>("/api/checkin"),
      ]);
      startTransition(() => {
        setAnalytics(nextAnalytics);
        setCheckin(nextCheckin);
      });
    } catch { /* silent */ }
  }

  // Slow loop (5 min) — health + summaries rarely change
  async function refreshSlow() {
    try {
      const [nextHealth, nextSummaries, nextCalendar] = await Promise.all([
        fetchJson<HealthResponse>("/api/healthz"),
        fetchJson<HourlySummary[]>("/api/hourly-summaries?limit=4").catch(() => [] as HourlySummary[]),
        fetchJson<CalendarResponse>("/api/calendar/today").catch(() => ({ events: [], ai_day_insight: null })),
      ]);
      startTransition(() => {
        setHealth(nextHealth);
        setHourlySummaries(nextSummaries);
        setCalendarEvents(nextCalendar.events ?? []);
        setAiDayInsight(nextCalendar.ai_day_insight ?? null);
      });
    } catch { /* silent */ }
  }

  async function reloadZones() {
    try {
      const response = await fetchJson<{ zones: ZoneRecord[] }>("/api/zones");
      startTransition(() => setZones(response.zones));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to load zones.");
    }
  }

  async function saveSettings(nextSettings: BackendSettings) {
    setErrorMessage("");
    try {
      await fetchJson("/api/settings", {
        method: "POST",
        body: JSON.stringify({
          capture_interval_seconds: nextSettings.capture_interval_seconds,
          tracking_enabled: nextSettings.tracking_enabled,
          ai_provider: nextSettings.ai_provider,
          ai_fallback_providers: nextSettings.ai_fallback_providers,
          ai_routing_mode: nextSettings.ai_routing_mode,
          llm_mode: nextSettings.llm_mode,
          hourly_summaries_enabled: nextSettings.hourly_summaries_enabled,
          user_timezone: nextSettings.user_timezone,
          privacy_mode: nextSettings.privacy_mode,
          calendar_sync_enabled: nextSettings.calendar_sync_enabled,
          calendar_ical_urls: nextSettings.calendar_ical_urls ?? (nextSettings.calendar_ical_url ? [nextSettings.calendar_ical_url] : []),
        }),
      });
      setStatusMessage("Settings saved.");
      await refreshCore();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to save settings.");
    }
  }

  useEffect(() => {
    void refreshCore();
    void refreshSlow();   // health + summaries on first load
    void reloadZones();

    // 60s — state + logs only (2 requests instead of 6). Skip when tab hidden.
    const liveInterval = window.setInterval(() => {
      if (!document.hidden) void refreshLive();
    }, 60_000);

    // 2 min — analytics + checkin. Skip when tab hidden.
    const analyticsInterval = window.setInterval(() => {
      if (!document.hidden) void refreshAnalytics();
    }, 2 * 60_000);

    // 2 min — health + summaries. Skip when tab hidden.
    const slowInterval = window.setInterval(() => {
      if (!document.hidden) void refreshSlow();
    }, 2 * 60_000);

    return () => {
      window.clearInterval(liveInterval);
      window.clearInterval(analyticsInterval);
      window.clearInterval(slowInterval);
    };
  }, []);

  useEffect(() => {
    if (!statusMessage) return undefined;
    const timer = window.setTimeout(() => setStatusMessage(""), 3000);
    return () => window.clearTimeout(timer);
  }, [statusMessage]);

  useEffect(() => {
    if (!errorMessage) return undefined;
    const timer = window.setTimeout(() => setErrorMessage(""), 8000);
    return () => window.clearTimeout(timer);
  }, [errorMessage]);

  if (isOffline) {
    return (
      <div className="offline-state">
        <p>Can't reach the backend.</p>
        <button className="primary-button" onClick={() => { setIsOffline(false); void refreshCore(); }}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <AppShell
        statusMessage={statusMessage}
        errorMessage={errorMessage}
        refreshing={refreshing}
        onRefresh={() => void refreshCore()}
        state={state}
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
                checkin={checkin}
                timezone={settings?.user_timezone}
                captureIntervalSeconds={settings?.capture_interval_seconds}
                initialLoading={initialLoading}
                onRefreshLogs={refreshCore}
                hourlySummaries={hourlySummaries}
                calendarEvents={calendarEvents}
                aiDayInsight={aiDayInsight}
              />
            }
          />
          <Route path="/setup" element={<SetupPage state={state} health={health} />} />
          <Route
            path="/diagnostics"
            element={<DiagnosticsPage state={state} health={health} settings={settings} />}
          />
          <Route
            path="/zones"
            element={
              <ZonesPage
                initialZones={zones}
                onReload={reloadZones}
                setStatusMessage={setStatusMessage}
                setErrorMessage={setErrorMessage}
              />
            }
          />
          <Route
            path="/settings"
            element={<SettingsPage settings={settings} onSave={saveSettings} />}
          />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
