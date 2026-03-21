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
  };
};

type CheckinResponse = {
  checkin?: string | null;
  guess?: string | null;
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

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ?? "";

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

function productivePulseData(hourlySummaries: HourlySummary[], productivePct?: number) {
  const values = hourlySummaries
    .slice(0, 10)
    .reverse()
    .map((s) => Math.max(12, Math.min(100, Math.round((s.productivity_score ?? 4.5) * 10))));
  if (values.length >= 6) return values;
  const seed = Math.max(20, Math.min(96, productivePct ?? 64));
  return Array.from({ length: 14 }, (_, i) => Math.max(18, Math.min(100, Math.round(seed + ((i % 4) - 2) * 8))));
}

function NavItem({ to, label, dim }: { to: string; label: string; dim?: boolean }) {
  return (
    <NavLink to={to} className={({ isActive }) => `nav-item${dim ? " nav-dim" : ""}${isActive ? " active" : ""}`}>
      {label}
    </NavLink>
  );
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
      <aside className="side-rail">
        <Link to="/today" className="brand-mark">
          <span className="brand-title">CHRONICLE</span>
        </Link>
        <nav className="side-rail-nav">
          <NavItem to="/today" label="Today" />
          <NavItem to="/zones" label="Places" />
          <NavItem to="/diagnostics" label="History" />
          <NavItem to="/settings" label="Archive" />
        </nav>
        <div className="sidebar-footer">
          <NavItem to="/setup" label="Support" dim />
          <NavItem to="/settings" label="Settings" dim />
          <button className="log-intent-btn" type="button">LOG INTENT</button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <span className="brand-title">CHRONICLE</span>
            <span className="topbar-status-tag">OPERATIONAL LOG</span>
          </div>

          <div className="topbar-actions">
            <button className="refresh-btn" onClick={onRefresh} type="button" disabled={refreshing}>
              {refreshing ? "SYNCHRONIZING..." : "REFRESH"}
            </button>
            <div className="user-avatar" style={{width: 36, height: 36, background: 'var(--panel-bright)', borderRadius: 2}}></div>
          </div>
        </header>

        <main className="content">
          {statusMessage && <div className="banner success">{statusMessage}</div>}
          {errorMessage && <div className="banner error">{errorMessage}</div>}
          {children}
        </main>

        <footer className="app-footer">
          <div className="app-footer-left">
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <span className={`sidebar-status-dot bg-${serviceTone(state?.service_health)}`} />
              <span>{state?.service_health === "ok" ? "SYSTEM UPLINK ACTIVE" : "SYSTEM OFFLINE"}</span>
            </div>
            <span>VERO OBSERVATORY</span>
          </div>
          <div className="app-footer-right">
            <span>{state?.current_location?.toUpperCase() ?? "AWAITING PLACE CONTEXT"}</span>
          </div>
        </footer>
      </div>
    </div>
  );
}

function TodayPage({
  state,
  analytics,
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

  async function handleChat() {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatSending(true);
    setChatInput("");
    try {
      await fetchJson("/api/chat", { method: "POST", body: JSON.stringify({ message: msg }) });
      onRefreshLogs();
    } finally { setChatSending(false); }
  }

  const pulseValues = productivePulseData(hourlySummaries, analytics?.productive_pct);

  return (
    <div className="editorial-page">
      <div className="editorial-grid">
        <div className="editorial-left">
          <section className="hero-section">
            <span className="section-eyebrow" style={{ color: 'var(--accent)' }}>SESSION ACTIVE</span>
            <h1 className="main-greeting">{timeGreeting()}</h1>

            <div className="intent-selection">
              <span className="section-eyebrow">INTENT SELECTION</span>
              <input
                className="editorial-intent-input"
                placeholder="Define your trajectory..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !chatSending) void handleChat(); }}
              />
            </div>

            <div className="recent-channels">
              <span className="section-eyebrow">RECENT CHANNELS</span>
              <div className="channel-btns">
                <button className="channel-btn">VS CODE</button>
                <button className="channel-btn">TERMINAL</button>
                <button className="channel-btn">DOCS</button>
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
                <svg className="meta-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
                <span>ENVIRONMENT: {state?.current_location?.toUpperCase() ?? "STABLE"}</span>
              </div>
              <div className="meta-item">
                <svg className="meta-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v10l4.5 4.5"/><circle cx="12" cy="12" r="10"/></svg>
                <span>OUTPUT: {analytics?.log_count ?? 0} LOGS / {analytics?.llm_used ?? 0} LLM</span>
              </div>
            </div>
          </article>

          <article className="editorial-card productivity-pulse">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span className="section-eyebrow">PRODUCTIVITY PULSE</span>
              <span className="pulse-pct">{analytics?.productive_pct ?? 0}%</span>
            </div>
            <span className="card-subtitle">High-Frequency Output</span>
            <div className="pulse-bars">
              {pulseValues.map((v, i) => <div key={i} className="pulse-bar-item" style={{ height: `${v}%` }} />)}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.55rem", color: "var(--muted)", fontWeight: 800, letterSpacing: '0.1em' }}>
              <span>08:00</span>
              <span style={{ color: 'var(--accent)' }}>LIVE NOW</span>
              <span>20:00</span>
            </div>
          </article>
        </div>
      </div>

      <footer className="editorial-footer">
        <div className="metric-group">
          <div className="metric-item">
            <span className="metric-value">{analytics?.productive_minutes ?? 0}m</span>
            <span className="metric-label">PRODUCTIVE</span>
          </div>
          <div className="metric-item">
            <span className="metric-value">{Math.max(0, (analytics?.total_active_minutes ?? 0) - (analytics?.productive_minutes ?? 0))}m</span>
            <span className="metric-label">ADMINISTRATIVE</span>
          </div>
          <div className="metric-item">
            <span className="metric-value">STABLE</span>
            <span className="metric-label">ENVIRONMENT</span>
          </div>
        </div>
        <div className="ticker">
          REFINING INTELLIGENCE FEED <span style={{ opacity: 0.3 }}>● ● ●</span>
        </div>
      </footer>
    </div>
  );
}

function Surface({ title, eyebrow, children }: { title: string; eyebrow?: string; children: ReactNode }) {
  return (
    <section className="surface" style={{ padding: '4rem', margin: '4rem', border: '1px solid var(--line)' }}>
      <div style={{ marginBottom: '3rem' }}>
        {eyebrow && <div className="section-eyebrow">{eyebrow}</div>}
        <h2 style={{ fontFamily: 'Newsreader', fontSize: '3rem', fontStyle: 'italic', fontWeight: 300, margin: 0 }}>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1.5rem 0', borderBottom: '1px solid var(--line)' }}>
      <span style={{ fontSize: '0.7rem', fontWeight: 800, letterSpacing: '0.1em', color: 'var(--muted)' }}>{label}</span>
      <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>{String(value ?? "—")}</span>
    </div>
  );
}

function DiagnosticsPage({ state, health, settings }: { state: DashboardState | null; health: HealthResponse | null; settings: BackendSettings | null }) {
  return (
    <div style={{ padding: '2rem' }}>
      <Surface title="Agent Diagnostics" eyebrow="System Health">
        <Field label="Service Health" value={health?.status} />
        <Field label="Last Heartbeat" value={state?.last_mac_heartbeat_age_seconds ? `${state.last_mac_heartbeat_age_seconds}s ago` : "Unknown"} />
        <Field label="Active Provider" value={health?.llm?.provider} />
        <Field label="Tracking" value={settings?.tracking_enabled ? "Enabled" : "Paused"} />
      </Surface>
    </div>
  );
}

function SettingsPage({ settings, onSave }: { settings: BackendSettings | null; onSave: (s: BackendSettings) => Promise<void> }) {
  const [draft, setDraft] = useState<BackendSettings | null>(settings);
  useEffect(() => { setDraft(settings); }, [settings]);
  if (!draft) return null;
  return (
    <div style={{ padding: '2rem' }}>
      <Surface title="System Settings" eyebrow="Configuration">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Tracking Enabled</span>
            <input type="checkbox" checked={draft.tracking_enabled} onChange={e => setDraft({ ...draft, tracking_enabled: e.target.checked })} />
          </label>
          <button className="log-intent-btn" style={{ width: 'auto', padding: '1rem 2rem' }} onClick={() => void onSave(draft)}>Save Changes</button>
        </div>
      </Surface>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [settings, setSettings] = useState<BackendSettings | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [hourlySummaries, setHourlySummaries] = useState<HourlySummary[]>([]);
  const [aiDayInsight, setAiDayInsight] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function refreshCore() {
    setRefreshing(true);
    try {
      const [st, se, an, lo, hs, ai] = await Promise.allSettled([
        fetchJson<DashboardState>("/api/state"),
        fetchJson<BackendSettings>("/api/settings"),
        fetchJson<Analytics>("/api/analytics/today"),
        fetchJson<ActivityLog[]>("/api/logs?limit=15"),
        fetchJson<HourlySummary[]>("/api/hourly-summaries?limit=4"),
        fetchJson<{ai_day_insight?: string}>("/api/calendar/today"),
      ]);
      if (st.status === "fulfilled") setState(st.value);
      if (se.status === "fulfilled") setSettings(se.value);
      if (an.status === "fulfilled") setAnalytics(an.value);
      if (lo.status === "fulfilled") setLogs(lo.value);
      if (hs.status === "fulfilled") setHourlySummaries(hs.value);
      if (ai.status === "fulfilled") setAiDayInsight(ai.value.ai_day_insight ?? null);
    } finally { setRefreshing(false); }
  }

  useEffect(() => {
    void refreshCore();
    const i = setInterval(() => { if (!document.hidden) void refreshCore(); }, 60000);
    return () => clearInterval(i);
  }, []);

  return (
    <BrowserRouter>
      <AppShell statusMessage={statusMessage} errorMessage={errorMessage} refreshing={refreshing} onRefresh={() => void refreshCore()} state={state}>
        <Routes>
          <Route path="/" element={<Navigate replace to="/today" />} />
          <Route path="/today" element={<TodayPage state={state} analytics={analytics} logs={logs} hourlySummaries={hourlySummaries} aiDayInsight={aiDayInsight} onRefreshLogs={refreshCore} />} />
          <Route path="/diagnostics" element={<DiagnosticsPage state={state} health={null} settings={settings} />} />
          <Route path="/settings" element={<SettingsPage settings={settings} onSave={async (s) => {
            await fetchJson("/api/settings", { method: "POST", body: JSON.stringify(s) });
            setStatusMessage("Settings updated.");
            void refreshCore();
          }} />} />
          <Route path="*" element={<Navigate replace to="/today" />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
