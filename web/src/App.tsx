import {
  startTransition,
  useDeferredValue,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  BrowserRouter,
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
  sleep_status_note?: string;
  service_health?: string;
  tracking_enabled?: string;
  capture_interval_seconds?: number;
  presence_state?: string;
  last_presence_change_at?: string;
  screen_state?: string;
  privacy_mode?: string;
  calendar_sync_enabled?: boolean;
  last_heartbeat_at?: string;
  last_capture_at?: string;
};

type BackendSettings = {
  capture_interval_seconds: number;
  polling_interval_seconds: number;
  tracking_enabled: boolean;
  backend_mode: string;
  ai_provider: string;
  llm_mode: string;
  hourly_summaries_enabled: boolean;
  classification_interval_seconds: number;
  llm_daily_cap: number;
  user_timezone: string;
  privacy_mode: "private" | "detailed";
  calendar_sync_enabled: boolean;
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

function formatTime(value?: string) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function intervalLabel(seconds?: number) {
  if (seconds === 60) return "1 minute";
  if (seconds === 300) return "5 minutes";
  if (seconds === 900) return "15 minutes";
  if (!seconds) return "Unknown";
  return `${seconds}s`;
}

function presenceLabel(value?: string) {
  switch ((value ?? "").toLowerCase()) {
    case "active":
      return "Active";
    case "idle":
      return "Idle";
    case "away":
      return "Away";
    case "locked":
      return "Locked";
    case "sleeping":
      return "Sleeping";
    default:
      return "Unknown";
  }
}

function privacyLabel(value?: string) {
  return value === "detailed" ? "Detailed capture" : "Private by default";
}

function serviceTone(value?: string) {
  if (value === "ok" || value === "online") return "good";
  if (value === "offline") return "bad";
  return "warn";
}

function AppShell({
  children,
  statusMessage,
  errorMessage,
  refreshing,
  onRefresh,
}: {
  children: ReactNode;
  statusMessage: string;
  errorMessage: string;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">Hosted beta</div>
          <h1>Vero dashboard</h1>
        </div>
        <div className="topbar-actions">
          <button
            className="secondary-button"
            onClick={onRefresh}
            type="button"
            disabled={refreshing}
            aria-busy={refreshing}
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <nav className="nav-list">
            <NavItem to="/today" label="Today" />
            <NavItem to="/setup" label="Setup" />
            <NavItem to="/diagnostics" label="Diagnostics" />
            <NavItem to="/zones" label="Zones" />
            <NavItem to="/settings" label="Settings" />
          </nav>
          <div className="sidebar-card">
            <div className="sidebar-card-title">Dashboard first</div>
            <p>
              The Mac side stays lightweight in the menu bar. Settings, privacy,
              zones, and diagnostics all live here in the dashboard.
            </p>
          </div>
        </aside>

        <main className="content">
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
    </div>
  );
}

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
    >
      {label}
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

function TodayPage({
  state,
  analytics,
  logs,
  checkin,
}: {
  state: DashboardState | null;
  analytics: Analytics | null;
  logs: ActivityLog[];
  checkin: CheckinResponse | null;
}) {
  const deferredLogs = useDeferredValue(logs);

  return (
    <div className="page-grid">
      <div className="stack">
        <Surface title="Today" eyebrow="Live view">
          <div className="hero-grid">
            <div>
              <h3 className="hero-title">
                {state?.current_activity_summary ?? "Waiting for your first capture"}
              </h3>
              <p className="hero-copy">
                Presence: <strong>{presenceLabel(state?.presence_state)}</strong> ·
                Capture cadence: <strong>{intervalLabel(state?.capture_interval_seconds)}</strong>
              </p>
            </div>
            <div className={`pill tone-${serviceTone(state?.service_health)}`}>
              {state?.mac_status?.replace(/_/g, " ") ?? "unknown"}
            </div>
          </div>
          <div className="stats-grid">
            <StatCard
              label="Active today"
              value={`${analytics?.total_active_minutes ?? 0} min`}
              note={`${analytics?.log_count ?? 0} captured intervals`}
            />
            <StatCard
              label="Productive"
              value={`${analytics?.productive_pct ?? 0}%`}
              note={`${analytics?.productive_minutes ?? 0} productive minutes`}
              tone="warn"
            />
            <StatCard
              label="AI budget"
              value={`${analytics?.llm_used ?? 0}/${analytics?.llm_cap ?? 0}`}
              note="Summaries fall back gracefully when this cap is reached"
              tone="good"
            />
          </div>
        </Surface>

        {checkin?.checkin ? (
          <Surface title="Pending check-in" eyebrow="Needs input">
            <p className="lead">{checkin.checkin}</p>
            {checkin.guess ? <p className="muted">Last guess: {checkin.guess}</p> : null}
          </Surface>
        ) : null}

        <Surface title="Recent timeline" eyebrow="Redacted by default">
          <div className="timeline">
            {deferredLogs.length ? (
              deferredLogs.map((entry) => (
                <article className="timeline-row" key={entry.id}>
                  <div className="timeline-time">{formatTime(entry.timestamp)}</div>
                  <div className="timeline-copy">
                    <strong>{entry.app_name || entry.location_label || entry.activity_type || "Activity"}</strong>
                    <p>{entry.window_title || entry.activity_type || entry.location_label || "No detail available"}</p>
                  </div>
                  <div className="timeline-meta">{presenceLabel(entry.presence_state)}</div>
                </article>
              ))
            ) : (
              <p className="empty-state">No activity has been recorded yet.</p>
            )}
          </div>
        </Surface>
      </div>

      <div className="stack">
        <Surface title="Device status" eyebrow="Mac health">
          <Field label="Status" value={state?.mac_status_reason ?? "Waiting for agent"} />
          <Field label="Presence" value={presenceLabel(state?.presence_state)} />
          <Field label="Last heartbeat" value={formatAge(state?.last_mac_heartbeat_age_seconds)} />
          <Field label="Last capture" value={formatAge(state?.last_mac_capture_age_seconds)} />
          <Field label="Location" value={state?.current_location ?? "No recent location"} />
          <Field label="Sleep" value={state?.sleep_status_note ?? "Unknown"} />
        </Surface>

        <Surface title="Privacy posture" eyebrow="Data handling">
          <p className="lead">{privacyLabel(state?.privacy_mode)}</p>
          <p className="muted">
            Browser titles and URLs stay redacted unless detailed capture is
            explicitly enabled in settings.
          </p>
        </Surface>
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

  return (
    <div className="stack">
      <Surface title="Setup" eyebrow="Hosted beta onboarding">
        <div className="step-grid">
          <SetupStep
            title="1. Launch the menu bar companion"
            status={heartbeatReady ? "Done" : "Waiting"}
            body="Open Vero once, save your backend URL and password/basic-auth value, then let it keep running from the menu bar."
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
            title="4. Add optional iPhone zones"
            status={state?.ios_recent_event ? "Active" : "Optional"}
            body="Use iPhone Shortcuts only if you want zone and sleep context."
          />
        </div>
      </Surface>

      <div className="page-grid">
        <Surface
          title="Mac install & repair"
          eyebrow="Native app"
          action={
            <a className="secondary-link" href="/setup/mac" target="_blank" rel="noreferrer">
              Open Mac setup
            </a>
          }
        >
          <p className="lead">
            Vero on Mac is a lightweight menu bar companion. Use this dashboard
            for cadence, privacy, diagnostics, zones, and ongoing management.
          </p>
          <p className="muted">
            After the first connection, the Mac side should mostly stay out of
            the way. Relaunch it only if you need to reconnect the helper or fix
            local permissions.
          </p>
        </Surface>

        <Surface
          title="Optional iPhone setup"
          eyebrow="Companion context"
          action={
            <a className="secondary-link" href="/setup/ios" target="_blank" rel="noreferrer">
              Open iPhone setup
            </a>
          }
        >
          <p className="lead">
            Zones and sleep signals are optional. Vero should still feel complete
            with just the Mac menu bar companion.
          </p>
          <p className="muted">
            Current backend health: {health?.status ?? "unknown"}.
          </p>
        </Surface>
      </div>
    </div>
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
        eyebrow="Optional iPhone context"
        action={
          <a className="secondary-link" href="/setup/ios" target="_blank" rel="noreferrer">
            Open iPhone setup
          </a>
        }
      >
        <p className="muted">
          Zones are optional. Keep them lean and meaningful so check-ins stay useful.
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

  useEffect(() => {
    setDraft(zone);
  }, [zone]);

  return (
    <article className="zone-card">
      <ZoneForm zone={draft} onChange={setDraft} />
      <div className="surface-actions">
        <button className="secondary-button" type="button" onClick={() => onSave(draft)}>
          Save
        </button>
        <button className="danger-button" type="button" onClick={() => onDelete(draft)}>
          Delete
        </button>
      </div>
    </article>
  );
}

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
        />
      </label>
      <label className="field">
        <span>Slug</span>
        <input
          value={zone.slug}
          onChange={(event) => onChange({ ...zone, slug: slugify(event.target.value) })}
        />
      </label>
      <label className="field">
        <span>Radius (meters)</span>
        <input
          type="number"
          min={25}
          max={5000}
          value={zone.radius_meters}
          onChange={(event) =>
            onChange({ ...zone, radius_meters: Number(event.target.value || 75) })
          }
        />
      </label>
      <label className="field">
        <span>Focus mode</span>
        <input
          value={zone.focus_mode}
          onChange={(event) => onChange({ ...zone, focus_mode: event.target.value })}
        />
      </label>
    </div>
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

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  if (!draft) {
    return <Surface title="Settings">Loading settings…</Surface>;
  }

  return (
    <div className="stack">
      <Surface title="Settings" eyebrow="Tracking & privacy">
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
              <option value={900}>15 minutes</option>
            </select>
          </label>

          <label className="field">
            <span>Privacy mode</span>
            <select
              value={draft.privacy_mode}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  privacy_mode: event.target.value as BackendSettings["privacy_mode"],
                })
              }
            >
              <option value="private">Private by default</option>
              <option value="detailed">Detailed capture</option>
            </select>
          </label>

          <label className="field">
            <span>AI provider</span>
            <select
              value={draft.ai_provider}
              onChange={(event) => setDraft({ ...draft, ai_provider: event.target.value })}
            >
              <option value="auto">Auto</option>
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>

          <label className="field">
            <span>Daily AI cap</span>
            <input
              type="number"
              min={1}
              max={500}
              value={draft.llm_daily_cap}
              onChange={(event) =>
                setDraft({ ...draft, llm_daily_cap: Number(event.target.value || 30) })
              }
            />
          </label>

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

          <label className="toggle-field">
            <span>Calendar sync</span>
            <input
              type="checkbox"
              checked={draft.calendar_sync_enabled}
              onChange={(event) =>
                setDraft({ ...draft, calendar_sync_enabled: event.target.checked })
              }
            />
          </label>
        </div>

        <div className="surface-actions">
          <button className="primary-button" type="button" onClick={() => onSave(draft)}>
            Save settings
          </button>
        </div>
      </Surface>
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
  const [refreshing, setRefreshing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function refreshCore() {
    setRefreshing(true);
    setErrorMessage("");
    try {
      const [nextState, nextSettings, nextAnalytics, nextLogs, nextHealth, nextCheckin] =
        await Promise.all([
          fetchJson<DashboardState>("/api/state"),
          fetchJson<BackendSettings>("/api/settings"),
          fetchJson<Analytics>("/api/analytics/today"),
          fetchJson<ActivityLog[]>("/api/logs?limit=15"),
          fetchJson<HealthResponse>("/api/healthz"),
          fetchJson<CheckinResponse>("/api/checkin"),
        ]);

      startTransition(() => {
        setState(nextState);
        setSettings(nextSettings);
        setAnalytics(nextAnalytics);
        setLogs(nextLogs);
        setHealth(nextHealth);
        setCheckin(nextCheckin);
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to refresh data.");
    } finally {
      setRefreshing(false);
    }
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
          llm_mode: nextSettings.llm_mode,
          hourly_summaries_enabled: nextSettings.hourly_summaries_enabled,
          llm_daily_cap: nextSettings.llm_daily_cap,
          user_timezone: nextSettings.user_timezone,
          privacy_mode: nextSettings.privacy_mode,
          calendar_sync_enabled: nextSettings.calendar_sync_enabled,
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
    void reloadZones();

    const interval = window.setInterval(() => {
      void refreshCore();
    }, 30_000);

    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!statusMessage) return undefined;
    const timer = window.setTimeout(() => setStatusMessage(""), 3000);
    return () => window.clearTimeout(timer);
  }, [statusMessage]);

  return (
    <BrowserRouter>
      <AppShell
        statusMessage={statusMessage}
        errorMessage={errorMessage}
        refreshing={refreshing}
        onRefresh={() => void refreshCore()}
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
