const API = '';

// ── Escape HTML to prevent XSS ──
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function escAttr(str) {
    return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function slugify(value) {
    return String(value || '')
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

function effectiveBackendBase() {
    const fromState = latestStates && latestStates.backend_target_url
        ? String(latestStates.backend_target_url).trim()
        : '';
    const fallback = window.location.origin || '';
    return (fromState || fallback || '').replace(/\/+$/, '');
}

function zoneAutomationUrls(slug) {
    const cleanSlug = slugify(slug || '');
    const base = effectiveBackendBase();
    return {
        arrive: `${base}/api/ios-zone-event?zone_slug=${encodeURIComponent(cleanSlug)}&transition=enter`,
        leave: `${base}/api/ios-zone-event?zone_slug=${encodeURIComponent(cleanSlug)}&transition=exit`,
    };
}

// ── DOM refs ──
const clockEl = document.getElementById('clock');
const macStatus = document.getElementById('mac-status');
const macDetail = document.getElementById('mac-detail');
const macOpenApp = document.getElementById('mac-open-app');
const macSetupLink = document.getElementById('mac-setup-link');
const iosStatus = document.getElementById('ios-status');
const iosDetail = document.getElementById('ios-detail');
const focusStatus = document.getElementById('focus-status');
const focusDetail = document.getElementById('focus-detail');
const activityCategory = document.getElementById('activity-category');
const activitySummary = document.getElementById('activity-summary');
const logsBody = document.getElementById('logs-body');
const refreshBtn = document.getElementById('refresh-btn');
const clearLogsBtn = document.getElementById('clear-logs-btn');
const themeToggleBtn = document.getElementById('theme-toggle-btn');
const pollingSlider = document.getElementById('polling-slider');
const pollingLabel = document.getElementById('polling-label');
const serviceStatusEl = document.getElementById('service-status');
const serviceDetailEl = document.getElementById('service-detail');
const calendarStatusEl = document.getElementById('calendar-status');
const calendarDetailEl = document.getElementById('calendar-detail');
const iosSetupStatusEl = document.getElementById('ios-setup-status');
const iosSetupDetailEl = document.getElementById('ios-setup-detail');
const nextStepStatusEl = document.getElementById('next-step-status');
const nextStepDetailEl = document.getElementById('next-step-detail');
const statActiveNote = document.getElementById('stat-active-note');
const statProductiveNote = document.getElementById('stat-productive-note');
let latestStates = null;
let uiTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
let lastAnalyticsRefreshMs = 0;

function parseServerTimestamp(value) {
    let raw = String(value || '').trim();
    if (!raw) return null;
    if (/[+-]\d{2}:\d{2}Z$/.test(raw)) raw = raw.slice(0, -1);
    if (/Z$|[+-]\d{2}:\d{2}$/.test(raw)) {
        const dt = new Date(raw);
        return Number.isNaN(dt.getTime()) ? null : dt;
    }
    const dt = new Date(`${raw}Z`);
    return Number.isNaN(dt.getTime()) ? null : dt;
}

function formatTime(value) {
    const dt = value instanceof Date ? value : parseServerTimestamp(value);
    if (!dt) return '';
    return dt.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
        timeZone: uiTimezone,
    });
}

function formatDate(value) {
    const dt = value instanceof Date ? value : parseServerTimestamp(value);
    if (!dt) return '';
    return dt.toLocaleDateString([], { month: 'short', day: 'numeric', timeZone: uiTimezone });
}

function localHourKey(value) {
    const dt = value instanceof Date ? value : parseServerTimestamp(value);
    if (!dt) return '';
    return new Intl.DateTimeFormat('sv-SE', {
        timeZone: uiTimezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        hour12: false,
    }).format(dt);
}

function localDateKey(value) {
    const dt = value instanceof Date ? value : parseServerTimestamp(value);
    if (!dt) return '';
    return new Intl.DateTimeFormat('sv-SE', {
        timeZone: uiTimezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).format(dt);
}

function localHourNumber(value) {
    const dt = value instanceof Date ? value : parseServerTimestamp(value);
    if (!dt) return null;
    const hourText = new Intl.DateTimeFormat('en-US', {
        timeZone: uiTimezone,
        hour: '2-digit',
        hour12: false,
    }).format(dt);
    const parsed = parseInt(hourText, 10);
    return Number.isNaN(parsed) ? null : parsed;
}

function timeAgo(timestamp) {
    const dt = timestamp instanceof Date ? timestamp : parseServerTimestamp(timestamp);
    if (!dt) return '';
    const now = new Date();
    const diffSeconds = Math.floor((now - dt) / 1000);
    if (diffSeconds < 60) return diffSeconds <= 1 ? 'just now' : `${diffSeconds}s ago`;
    const diffMinutes = Math.floor(diffSeconds / 60);
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
}

// ── Theme Toggle ──
const THEME_KEY = 'vero_theme';

function initTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY) || 'dark';
    applyTheme(savedTheme);
}

function applyTheme(theme) {
    if (theme === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
        if (themeToggleBtn) themeToggleBtn.textContent = '🌙';
    } else {
        document.documentElement.removeAttribute('data-theme');
        if (themeToggleBtn) themeToggleBtn.textContent = '☀️';
    }
    localStorage.setItem(THEME_KEY, theme);
}

function toggleTheme() {
    const current = localStorage.getItem(THEME_KEY) || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
}

// ── Clock ──
function updateClock() {
    if (clockEl) {
        clockEl.textContent = new Date().toLocaleString(undefined, {
            weekday: 'short', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            hour12: true,
            timeZone: uiTimezone,
        });
    }
}
setInterval(updateClock, 1000);
updateClock();

// ── Category labels and colors ──
const CAT_LABELS = {
    studying: 'Studying', working: 'Working', entertainment: 'Entertainment',
    social_media: 'Social Media', gaming: 'Gaming', creative: 'Creative',
    break: 'Break', idle: 'Idle', other: 'Other', unknown: 'Analyzing...',
};

const PRODUCTIVE = new Set(['studying', 'working', 'creative']);
const DISTRACTED = new Set(['entertainment', 'social_media', 'gaming']);

// Handle quick action pills
function setChatContext(contextText) {
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = `I'm ${contextText.toLowerCase()}`;
        input.focus();
    }
}

// ── SSE: real-time data stream ──
let eventSource = null;
let sseConnected = false;

function connectSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource(`${API}/api/stream`);
    eventSource.onmessage = (e) => {
        sseConnected = true;
        try {
            const data = JSON.parse(e.data);
            if (data.states && data.logs) updateUI(data.logs, data.states);
        } catch { }
    };
    eventSource.onerror = () => {
        sseConnected = false;
        eventSource.close();
        setTimeout(connectSSE, 3000);
    };
}

// ── Fallback polling ──
async function fetchData(force = false) {
    if (sseConnected && !force) return;
    try {
        const [logsRes, stateRes] = await Promise.all([
            fetch(`${API}/api/logs?limit=15`),
            fetch(`${API}/api/state`),
        ]);
        const logs = await logsRes.json();
        const states = await stateRes.json();
        updateUI(logs, states);
    } catch (err) { }
}

// ── Update all UI ──
function updateUI(logs, states) {
    latestStates = states;
    if (states && states.user_timezone) uiTimezone = states.user_timezone;

    // Mac Card
    const isMacBrowser = /Mac/.test(navigator.platform || navigator.userAgent || '');
    const macState = states.mac_status || (states.mac_online === true ? 'online' : 'offline');
    const latestMac = logs.find(l => l.device === 'mac');
    const latestMacApp = latestMac && latestMac.app_name ? latestMac.app_name : '';

    if (macOpenApp) {
        macOpenApp.href = states.mac_launch_url || 'vero://open';
        macOpenApp.classList.toggle('hidden', !(isMacBrowser && macState === 'offline'));
    }
    if (macSetupLink) {
        macSetupLink.classList.toggle('hidden', macState === 'online');
    }

    if (macStatus) {
        const cardMac = document.getElementById('card-mac');
        if (macState === 'offline') {
            macStatus.textContent = 'Offline';
            macStatus.className = 'status-value color-red';
            const mins = states.last_mac_heartbeat_age_seconds != null ? Math.max(1, Math.ceil(states.last_mac_heartbeat_age_seconds / 60)) : '?';
            macDetail.textContent = states.mac_status_reason || `Last heartbeat ${mins}m ago`;
        } else if (macState === 'degraded' || macState === 'paused') {
            macStatus.textContent = macState === 'paused' ? 'Paused' : 'Needs Attention';
            macStatus.className = 'status-value color-amber';
            macDetail.textContent = states.mac_status_reason || 'Check permissions or tracking toggle';
        } else {
            macStatus.textContent = 'Online';
            macStatus.className = 'status-value color-green';
            macDetail.textContent = latestMacApp || (states.mac_idle ? 'Idle right now' : 'Agent connected');
        }
    }

    // iOS Card
    const latestIos = logs.find(l => l.device === 'ios');
    if (iosStatus && latestIos) {
        const zone = latestIos.location_label || 'Unknown';
        const trans = (latestIos.activity_type || '').toLowerCase();
        const prefix = trans.includes('enter') ? 'In' : trans.includes('leave') ? 'Left' : 'At';
        iosStatus.textContent = `${prefix} ${zone}`;
        iosStatus.className = 'status-value color-green';
        const batt = latestIos.battery_pct != null ? ` · ${latestIos.battery_pct}% battery` : '';
        iosDetail.textContent = timeAgo(latestIos.timestamp) + batt;
    } else if (iosStatus) {
        iosStatus.textContent = states.ios_recent_ping ? 'Connected' : 'Idle';
        iosStatus.className = states.ios_recent_ping ? 'status-value color-green' : 'status-value color-muted';
        iosDetail.textContent = states.ios_recent_ping ? 'Tracking' : 'No pings received';
    }

    // Sleep context — Mac activity overrides phone-based sleep inference
    if (focusStatus) {
        const macActive = states.mac_status === 'online';
        const sleepLikely = !macActive && String(states.likely_asleep || 'false') === 'true';
        if (states.current_intent) {
            focusStatus.textContent = `Awake · ${states.current_intent}`;
            focusStatus.className = 'status-value color-green';
            focusDetail.textContent = 'Intent overrides sleep inference.';
        } else if (macActive) {
            focusStatus.textContent = 'Likely Awake';
            focusStatus.className = 'status-value color-primary';
            focusDetail.textContent = 'Mac is active.';
        } else {
            focusStatus.textContent = sleepLikely ? 'Likely Asleep' : 'Likely Awake';
            focusStatus.className = sleepLikely ? 'status-value color-muted' : 'status-value color-primary';
            focusDetail.textContent = states.likely_asleep_reason || states.sleep_status_note || 'Waiting for events.';
        }
    }

    // AI Activity
    if (activityCategory) {
        const cat = states.current_activity_category || 'unknown';
        activityCategory.textContent = CAT_LABELS[cat] || cat;
        activitySummary.textContent = states.current_activity_summary || '\u2014';
        activityCategory.className = PRODUCTIVE.has(cat) ? 'status-value color-green' : DISTRACTED.has(cat) ? 'status-value color-red' : 'status-value color-primary';
    }

    // Logs Table
    if (logsBody) {
        logsBody.innerHTML = '';
        logs.forEach((entry, i) => {
            const tr = document.createElement('tr');
            // Disabled: activity insight modal on row click
            // tr.onclick = () => openSummaryModal(entry.id);

            const tdTime = document.createElement('td');
            tdTime.textContent = formatTime(entry.timestamp);

            const tdDevice = document.createElement('td');
            tdDevice.textContent = entry.device === 'mac' ? 'Mac' : 'iPhone';

            const tdActivity = document.createElement('td');
            tdActivity.textContent = entry.device === 'mac' ? (entry.app_name || '') : (entry.activity_type || 'Ping');

            const tdContext = document.createElement('td');
            if (entry.device === 'mac' && entry.window_title) {
                const pill = document.createElement('span');
                pill.className = 'tab-pill';
                pill.textContent = entry.window_title.substring(0, 50) + (entry.window_title.length > 50 ? '...' : '');
                tdContext.appendChild(pill);
            } else if (entry.device !== 'mac') {
                tdContext.textContent = entry.location_label || '\u2014';
            }

            tr.append(tdTime, tdDevice, tdActivity, tdContext);
            logsBody.appendChild(tr);
        });
    }

    refreshAnalyticsIfStale();
    updateServicePanel();
}

// ── Analytics ──
async function fetchAnalytics() {
    try {
        const res = await fetch(`${API}/api/analytics/today`);
        const data = await res.json();
        renderAnalytics(data.category_minutes || {});
        renderStats(data);
        lastAnalyticsRefreshMs = Date.now();
    } catch { }
}

function refreshAnalyticsIfStale(maxAgeMs = 60000) {
    if (Date.now() - lastAnalyticsRefreshMs < maxAgeMs) return;
    fetchAnalytics();
}

function renderStats(data) {
    const h = Math.floor(data.total_active_minutes / 60);
    const m = Math.round(data.total_active_minutes % 60);
    if (document.getElementById('stat-active')) document.getElementById('stat-active').textContent = `${h}h ${m}m`;
    if (document.getElementById('stat-productive')) document.getElementById('stat-productive').textContent = `${data.productive_pct}%`;
    if (document.getElementById('stat-llm')) document.getElementById('stat-llm').textContent = `${data.llm_used}/${data.llm_cap}`;

    if (statActiveNote) {
        const fresh = data.data_freshness_seconds != null ? `${Math.floor(data.data_freshness_seconds / 60)}m ago` : 'n/a';
        statActiveNote.textContent = data.total_active_minutes > 0 ? `Last telemetry: ${fresh}` : 'Collecting data...';
    }
    if (statProductiveNote) {
        statProductiveNote.textContent = data.total_active_minutes > 0 ? `${Math.round(data.productive_minutes)} productive mins` : 'Waiting for data...';
    }
}

function renderAnalytics(data) {
    const container = document.getElementById('analytics-chart');
    if (!container) return;
    const entries = Object.entries(data);
    if (!entries.length) {
        container.innerHTML = '<p class="text-muted">No data today.</p>';
        return;
    }

    let totalMins = 0;
    for (const d of Object.values(data)) totalMins += d;
    if (totalMins === 0) return;

    const sorted = entries.sort((a, b) => b[1] - a[1]);
    let trackHtml = '<div class="stacked-bar-track">';
    let labelsHtml = '<div class="stacked-bar-labels">';

    sorted.forEach(([rawCat, durationMins]) => {
        const cat = rawCat.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z-]/g, '');
        const pct = (durationMins / totalMins) * 100;
        const time = durationMins >= 60 ? `${Math.floor(durationMins / 60)}h ${Math.floor(durationMins % 60)}m` : `${Math.floor(durationMins)}m`;

        trackHtml += `<div class="stacked-bar-fill" style="width: ${pct}%; background: var(--cat-${cat}, var(--text-muted));" title="${rawCat}: ${time}"></div>`;
        labelsHtml += `<div class="chart-label-item"><div class="chart-label-color" style="background: var(--cat-${cat}, var(--text-muted));"></div><span>${rawCat} (${time})</span></div>`;
    });

    container.innerHTML = trackHtml + '</div>' + labelsHtml + '</div>';
}

// ── Hourly Summaries & Feedback ──
async function fetchHourlySummaries() {
    const list = document.getElementById('summaries-list');
    if (!list) return;
    try {
        const res = await fetch(`${API}/api/hourly-summaries?limit=6`);
        const data = await res.json();

        if (!data.length) {
            list.innerHTML = '<p class="text-muted">No summaries yet.</p>';
            return;
        }

        list.innerHTML = data.map(s => {
            const date = parseServerTimestamp(s.hour_start_local || s.hour_start);
            const endDate = date ? new Date(date.getTime() + 60 * 60 * 1000) : null;
            const fmt = { hour: '2-digit', minute: '2-digit', hour12: true };
            const timeStr = date
                ? `${date.toLocaleTimeString([], fmt)} – ${endDate.toLocaleTimeString([], fmt)}`
                : 'Previous Hour';
            const score = s.productivity_score != null ? s.productivity_score.toFixed(1) : '—';
            const scoreColor = s.productivity_score >= 7 ? 'var(--accent-green)' : s.productivity_score >= 4 ? 'var(--accent-amber)' : 'var(--accent-red)';
            const hourStartISO = (s.hour_start_utc || s.hour_start || '').replace(/Z$/, '');

            return `<div class="summary-card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span class="summary-time">${timeStr}</span>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="color:${scoreColor};font-weight:600;font-size:12px;">${score}/10</span>
                        <button class="recap-delete-btn" data-summary-id="${s.id}" title="Delete recap">×</button>
                    </div>
                </div>
                <p style="font-size: 13px; line-height:1.5;">${esc(s.summary_text)}</p>
                <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:12px;">
                    <input type="text" placeholder="Something wrong? Correction..." class="recap-feedback-input"
                           data-hour-start="${escAttr(hourStartISO)}" data-original="${escAttr(s.summary_text)}" style="margin-top:0;">
                    <button class="recap-feedback-btn" data-hour-start="${escAttr(hourStartISO)}">Send Correction</button>
                </div>
            </div>`;
        }).join('');
        attachFeedbackListeners();
    } catch { }
}

function attachFeedbackListeners() {
    document.querySelectorAll('.recap-delete-btn').forEach(btn => {
        btn.onclick = async () => {
            const id = btn.dataset.summaryId;
            await fetch(`${API}/api/hourly-summaries/${id}`, { method: 'DELETE' });
            fetchHourlySummaries();
        };
    });
    document.querySelectorAll('.recap-feedback-btn').forEach(btn => {
        btn.onclick = async () => {
            const hourStart = btn.dataset.hourStart;
            const input = btn.parentElement.querySelector('.recap-feedback-input');
            const feedback = input.value.trim();
            if (!feedback) return;

            btn.disabled = true;
            btn.textContent = 'Sending...';
            try {
                const res = await fetch(`${API}/api/recap-feedback`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hour_start: hourStart, feedback, original_summary: input.dataset.original })
                });
                const r = await res.json();
                if (r.status === 'updated') {
                    alert('Recap updated!');
                    fetchHourlySummaries();
                } else {
                    alert(r.message || 'Saved feedback.');
                }
            } catch { }
            btn.disabled = false;
            btn.textContent = 'Send Correction';
        };
    });
}

async function triggerHourlyRecap() {
    const btn = document.getElementById('trigger-recap-btn');
    btn.textContent = 'Generating...';
    btn.disabled = true;
    try {
        await fetch(`${API}/api/trigger-hourly-summary`, { method: 'POST' });
        setTimeout(fetchHourlySummaries, 8000);
    } catch { }
    setTimeout(() => { btn.textContent = 'Generate Now'; btn.disabled = false; }, 3000);
}

// ── Onboarding ──
async function checkOnboarding() {
    if (localStorage.getItem('vero_onboarded')) return;
    const overlay = document.getElementById('onboarding-overlay');
    if (overlay) overlay.classList.remove('hidden');
    // Basic detection
    document.getElementById('onboard-tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function nextOnboardStep(n) {
    document.querySelectorAll('.onboarding-step').forEach(s => s.classList.add('hidden'));
    document.getElementById(`onboard-step-${n}`).classList.remove('hidden');
}

function completeOnboarding() {
    document.getElementById('onboarding-overlay').classList.add('hidden');
    localStorage.setItem('vero_onboarded', 'true');
}

// ── Settings Drawer ──
function openSettings() {
    document.getElementById('settings-drawer').classList.remove('hidden');
    document.getElementById('settings-backdrop').classList.remove('hidden');
    loadSettings();
}

function closeSettings() {
    document.getElementById('settings-drawer').classList.add('hidden');
    document.getElementById('settings-backdrop').classList.add('hidden');
}

async function loadSettings() {
    try {
        const res = await fetch(`${API}/api/settings`);
        const s = await res.json();
        document.getElementById('setting-tracking').checked = s.tracking_enabled;
        document.getElementById('setting-polling').value = s.polling_interval_seconds;
        document.getElementById('setting-llm-cap').value = s.llm_daily_cap;
        document.getElementById('setting-hourly').checked = s.hourly_summaries_enabled;

        // Populate and select timezone
        const sel = document.getElementById('setting-timezone');
        if (sel && sel.options.length === 0) {
            const tzs = ['America/Los_Angeles', 'America/New_York', 'Europe/London', 'Europe/Paris', 'Asia/Tokyo', 'UTC'];
            tzs.forEach(tz => {
                const o = document.createElement('option');
                o.value = tz; o.textContent = tz; sel.appendChild(o);
            });
        }
        if (s.user_timezone) sel.value = s.user_timezone;

        fetchZones();
    } catch { }
}

document.getElementById('settings-save-btn').onclick = async () => {
    const payload = {
        tracking_enabled: document.getElementById('setting-tracking').checked,
        polling_interval_seconds: parseInt(document.getElementById('setting-polling').value),
        llm_daily_cap: parseInt(document.getElementById('setting-llm-cap').value),
        hourly_summaries_enabled: document.getElementById('setting-hourly').checked,
        user_timezone: document.getElementById('setting-timezone').value,
    };
    try {
        await fetch(`${API}/api/settings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        updateTrackingUI(payload.tracking_enabled);
        closeSettings();
    } catch { }
};

async function fetchZones() {
    const list = document.getElementById('zones-list');
    if (!list) return;
    try {
        const res = await fetch(`${API}/api/zones`);
        const data = await res.json();
        const zones = data.zones || [];
        if (!zones.length) {
            list.innerHTML = '<p class="text-muted">No zones defined.</p>';
            return;
        }
        list.innerHTML = zones.map(z => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:10px; background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-input); margin-bottom:8px;">
                <div>
                    <div style="font-weight:600; font-size:13px; color:var(--text-primary)">${esc(z.name)}</div>
                    <div style="font-size:11px; color:var(--text-muted)">Radius: ${z.radius_meters}m • Type: ${z.zone_type}</div>
                </div>
                <button class="icon-btn" onclick="deleteZone(${z.id})" style="color:var(--accent-red)">×</button>
            </div>
        `).join('');
    } catch { }
}

async function addZone() {
    const name = prompt("Zone Name (e.g. Work, Gym):");
    if (!name) return;
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const radius = prompt("Radius in meters (default 75):") || "75";
    try {
        await fetch(`${API}/api/zones`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, slug, radius_meters: parseInt(radius), zone_type: 'custom' })
        });
        fetchZones();
    } catch (e) { alert("Failed to add zone"); }
}

window.deleteZone = async function (id) {
    if (!confirm("Delete this zone?")) return;
    try {
        await fetch(`${API}/api/zones/${id}`, { method: 'DELETE' });
        fetchZones();
    } catch (e) { }
}


// ── Tracking Toggle UI ──
let isTrackingEnabled = true;
function updateTrackingUI(enabled) {
    isTrackingEnabled = enabled;
    const btn = document.getElementById('toggle-tracking-btn');
    const pulse = document.getElementById('tracking-pulse');
    const badge = document.getElementById('tracking-badge');
    if (btn) {
        btn.textContent = enabled ? 'Tracking: ON' : 'Tracking: OFF';
        btn.className = `toggle-btn ${enabled ? 'active' : 'inactive'}`;
    }
    if (pulse) pulse.classList.toggle('inactive', !enabled);
    if (badge) {
        badge.textContent = enabled ? 'Live' : 'Paused';
        badge.className = `badge ${enabled ? '' : 'inactive'}`;
    }
}

document.getElementById('toggle-tracking-btn').addEventListener('click', async () => {
    const next = !isTrackingEnabled;
    try {
        await fetch(`${API}/api/settings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tracking_enabled: next })
        });
        updateTrackingUI(next);
    } catch { }
});

// ── Interval Pills ──
const intervalPillsContainer = document.getElementById('interval-pills');
if (intervalPillsContainer) {
    intervalPillsContainer.addEventListener('click', async (e) => {
        const pill = e.target.closest('[data-val]');
        if (!pill) return;

        const mins = parseInt(pill.dataset.val);
        console.log(`[Interval Pills] Changing polling interval to ${mins} minutes`);

        // Update UI immediately
        document.querySelectorAll('#interval-pills [data-val]').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');

        // Send to backend
        try {
            const response = await fetch(`${API}/api/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ polling_interval_seconds: mins * 60 })
            });
            if (response.ok) {
                console.log(`[Interval Pills] Successfully saved: ${mins}m`);
            } else {
                console.warn(`[Interval Pills] API returned status ${response.status}`);
            }
        } catch (err) {
            console.error(`[Interval Pills] Error:`, err);
        }
    });
}

// ── Chat ──
async function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    const btn = document.getElementById('chat-send');
    btn.textContent = '...';
    try {
        const res = await fetch(`${API}/api/chat`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        if (res.ok) {
            fetchChatHistory();
        }
    } catch { }
    btn.textContent = 'Send';
}

document.getElementById('chat-send').onclick = sendChat;
document.getElementById('chat-input').onkeydown = (e) => { if (e.key === 'Enter') sendChat(); };

async function fetchChatHistory() {
    const list = document.getElementById('chat-history-list');
    if (!list) return;
    try {
        const res = await fetch(`${API}/api/chat/history`);
        const data = await res.json();
        const messages = (data.messages || []).slice(-8);
        if (!messages.length) {
            list.innerHTML = '<p class="empty-state">No chat yet.</p>';
            return;
        }
        list.innerHTML = messages.map((turn) => {
            const time = formatTime(turn.time) || (turn.time ? new Date(turn.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
            return `
            <div class="chat-turn">
                ${time ? `<div class="chat-turn-time">${esc(time)}</div>` : ''}
                ${turn.user ? `<div class="chat-message chat-message-user">
                    <div class="chat-message-label">You</div>
                    <div class="chat-message-text">${esc(turn.user)}</div>
                </div>` : ''}
                ${turn.reply ? `<div class="chat-message chat-message-reply">
                    <div class="chat-message-label">Vero</div>
                    <div class="chat-message-text">${esc(turn.reply)}</div>
                </div>` : ''}
            </div>
            `;
        }).join('');
    } catch {
        list.innerHTML = '<p class="empty-state">Could not load chat history.</p>';
    }
}

// ── Check-In System ──
const checkinBanner = document.getElementById('checkin-banner');
const checkinMessage = document.getElementById('checkin-message');
const checkinConfirm = document.getElementById('checkin-confirm');
const checkinCorrection = document.getElementById('checkin-correction');
const checkinSend = document.getElementById('checkin-send');
const checkinSnooze = document.getElementById('checkin-snooze');
const checkinDismiss = document.getElementById('checkin-dismiss');

async function fetchCheckin() {
    try {
        const res = await fetch(`${API}/api/checkin`);
        const data = await res.json();
        if (data.checkin) {
            const ageHint = data.age_seconds != null && data.age_seconds > 0
                ? ` (${Math.floor(data.age_seconds / 60)}m old)`
                : '';
            checkinMessage.textContent = `Just checking in — ${data.checkin}${ageHint}`;
            checkinBanner.classList.remove('hidden');
            if (data.checkin !== lastCheckinNotification) {
                lastCheckinNotification = data.checkin;
                maybeNotify('Vero', data.checkin, 'checkin');
            }
        } else {
            checkinBanner.classList.add('hidden');
            lastCheckinNotification = '';
        }
    } catch { }
}

// ── Modal ──
function openSummaryModal(logId) {
    const modal = document.getElementById('summary-modal');
    modal.classList.remove('hidden');
    const text = document.getElementById('summary-text');
    text.textContent = 'Analyzing...';
    fetch(`${API}/api/summary/${logId}`)
        .then(r => r.json())
        .then(d => { text.textContent = d.summary_text || d.summary || 'No summary available.'; })
        .catch(() => { text.textContent = 'Error loading summary.'; });
}
function closeSummaryModal() { document.getElementById('summary-modal').classList.add('hidden'); }

// ── Refresh Button ──
if (refreshBtn) {
    refreshBtn.onclick = () => {
        fetch(`${API}/api/refresh-app-categories`, { method: 'POST' }).catch(() => { });
        fetchData(true); fetchAnalytics(); fetchHourlySummaries(); fetchChatHistory();
    };
}

// ── Service Panel ──
async function updateServicePanel() {
    function setCol(dotId, statusId, detailId, state, statusText, detailText) {
        const dot = document.getElementById(dotId);
        const statusEl = document.getElementById(statusId);
        const detailEl = document.getElementById(detailId);
        if (!dot || !statusEl) return;
        dot.className = 'status-dot ' + state;
        statusEl.className = 'status-text' + (state === 'checking' ? ' checking' : '');
        statusEl.textContent = statusText;
        if (detailEl) detailEl.textContent = detailText;
    }

    // Service Health — reuse latestStates (already fetched by SSE/polling)
    if (latestStates) {
        setCol('service-dot', 'service-status', 'service-detail',
            'green', 'Healthy', 'Backend connected');
    } else {
        setCol('service-dot', 'service-status', 'service-detail',
            'red', 'Offline', 'Cannot reach backend');
    }

    // Calendar Sync — green when mac agent is online
    const macOk = latestStates && latestStates.mac_status === 'online';
    setCol('calendar-dot', 'calendar-status', 'calendar-detail',
        macOk ? 'green' : 'checking',
        macOk ? 'Active' : 'Waiting',
        macOk ? 'Agent writing events' : 'Mac agent offline');

    // Update Footer Prompt
    if (nextStepStatusEl && nextStepDetailEl) {
        if (macOk) {
            nextStepStatusEl.textContent = 'Mac App Active';
            nextStepDetailEl.textContent = 'Agent is connected';
        } else {
            nextStepStatusEl.textContent = 'Open Mac App';
            nextStepDetailEl.textContent = 'Ensure agent is running';
        }
    }

    // iPhone Setup — use recent iOS activity as the signal
    const iosRecent = (() => {
        if (!latestStates) return false;
        const lastPing = parseServerTimestamp(latestStates.last_ios_ping) || 0;
        const lastEvent = parseServerTimestamp(latestStates.last_ios_event) || 0;
        const maxAge = 24 * 60 * 60 * 1000; // 24 hours
        const now = Date.now();
        return (now - lastPing < maxAge) || (now - lastEvent < maxAge);
    })();
    setCol('ios-dot', 'ios-setup-status', 'ios-setup-detail',
        iosRecent ? 'green' : 'checking',
        iosRecent ? 'Active' : 'Not seen recently',
        iosRecent ? 'iPhone reporting' : 'Open Shortcuts on iPhone');
}


// ── Init ──
connectSSE();
fetchData();
fetchAnalytics();
fetchHourlySummaries();
fetchChatHistory();
updateServicePanel();
initTheme();
checkOnboarding();
setInterval(fetchData, 60000);
setInterval(updateServicePanel, 30000);
