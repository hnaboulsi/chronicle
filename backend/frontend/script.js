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
let latestStates = null;
let uiTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

function parseServerTimestamp(value) {
    const raw = String(value || '').trim();
    if (!raw) return null;
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

// ── Clock ──
function updateClock() {
    clockEl.textContent = new Date().toLocaleString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: true,
        timeZone: uiTimezone,
    });
}
setInterval(updateClock, 1000);
updateClock();

// ── Category labels and colors ──
const CAT_LABELS = {
    studying: 'Studying', working: 'Working', entertainment: 'Entertainment',
    social_media: 'Social Media', gaming: 'Gaming', creative: 'Creative',
    break: 'Break', idle: 'Idle', unknown: 'Analyzing...',
};

const CAT_COLORS = {
    studying: 'var(--cat-studying)', working: 'var(--cat-working)', creative: 'var(--cat-creative)',
    entertainment: 'var(--cat-entertainment)', social_media: 'var(--cat-social-media)',
    gaming: 'var(--cat-gaming)', break: 'var(--cat-break)', idle: 'var(--cat-idle)',
};

const PRODUCTIVE = new Set(['studying', 'working', 'creative']);
const DISTRACTED = new Set(['entertainment', 'social_media', 'gaming']);

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
        // Reconnect after a short delay (server closes after 5 min to save resources)
        setTimeout(connectSSE, 3000);
    };
}

// ── Fallback polling (if SSE fails) ──
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
    } catch (err) {
        console.error('Fetch error:', err);
    }
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
    const launchUrl = states.mac_launch_url || 'vero://open';
    if (macOpenApp) {
        macOpenApp.href = launchUrl;
        macOpenApp.classList.toggle('hidden', !(isMacBrowser && macState === 'offline'));
    }

    if (macState === 'offline') {
        macStatus.textContent = 'Offline';
        macStatus.style.color = '#EF4444';
        if (states.last_mac_heartbeat_age_seconds != null) {
            const mins = Math.max(1, Math.ceil(states.last_mac_heartbeat_age_seconds / 60));
            macDetail.textContent = states.mac_status_reason || `Last heartbeat ${mins}m ago`;
        } else {
            macDetail.textContent = states.mac_status_reason || 'Not connected';
        }
        macDetail.style.color = '#9CA3AF';
    } else if (macState === 'degraded') {
        macStatus.textContent = 'Needs Access';
        macStatus.style.color = '#D97706';
        macDetail.textContent = states.mac_status_reason || 'Grant Accessibility and browser permissions';
        macDetail.style.color = '#6B7280';
    } else if (macState === 'paused') {
        macStatus.textContent = 'Paused';
        macStatus.style.color = '#D97706';
        macDetail.textContent = states.mac_status_reason || 'Tracking is paused';
        macDetail.style.color = '#6B7280';
    } else if (macState === 'online_idle') {
        macStatus.textContent = 'Online, idle';
        macStatus.style.color = '#111827';
        macDetail.textContent = latestMacApp || states.mac_status_reason || 'Agent connected';
        macDetail.style.color = '#6B7280';
    } else {
        macStatus.textContent = 'Online';
        macStatus.style.color = '#111827';
        macDetail.textContent = latestMacApp || states.mac_status_reason || 'Agent connected';
        macDetail.style.color = '#6B7280';
    }

    // iOS Card
    const latestIos = logs.find(l => l.device === 'ios');
    if (latestIos) {
        iosStatus.textContent = latestIos.location_label || 'Connected';
        iosStatus.style.color = '#16A34A';
        const battStr = latestIos.battery_pct != null ? ` · ${latestIos.battery_pct}% battery` : '';
        iosDetail.textContent = (latestIos.activity_type || 'Tracking') + battStr;
        iosDetail.style.color = '#6B7280';
    } else {
        iosStatus.textContent = states.ios_recent_ping ? 'Connected' : 'Idle';
        iosStatus.style.color = states.ios_recent_ping ? '#16A34A' : '#9CA3AF';
        iosDetail.textContent = states.ios_recent_ping ? 'Tracking location' : 'No pings received';
        iosDetail.style.color = '#9CA3AF';
    }

    // Focus Mode
    const isStudy = states.study_mode === 'active';
    focusStatus.textContent = isStudy ? 'Study Mode' : 'Off';
    focusStatus.style.color = isStudy ? '#D97706' : '#6B7280';
    focusDetail.textContent = isStudy ? 'Distraction alerts on' : 'Normal';

    // AI Reading
    const cat = states.current_activity_category || 'unknown';
    activityCategory.textContent = CAT_LABELS[cat] || cat;
    activitySummary.textContent = states.current_activity_summary || '\u2014';
    activityCategory.style.color = PRODUCTIVE.has(cat) ? '#16A34A' : DISTRACTED.has(cat) ? '#EF4444' : '#111827';

    // Logs Table
    logsBody.innerHTML = '';
    logs.forEach((entry, i) => {
        const tr = document.createElement('tr');
        tr.className = 'fade-in';
        tr.style.animationDelay = `${i * 0.03}s`;

        const time = formatTime(entry.timestamp);
        const isMac = entry.device === 'mac';

        const tdTime = document.createElement('td');
        tdTime.textContent = time;

        const tdDevice = document.createElement('td');
        tdDevice.textContent = isMac ? 'Mac' : 'iPhone';

        const tdActivity = document.createElement('td');
        tdActivity.textContent = isMac ? (entry.app_name || '') : (entry.activity_type || 'Ping');

        const tdContext = document.createElement('td');
        if (isMac && entry.window_title) {
            const pill = document.createElement('span');
            pill.className = 'tab-pill';
            let t = entry.window_title;
            if (t.length > 50) t = t.substring(0, 50) + '...';
            pill.textContent = t;
            tdContext.appendChild(pill);
        } else if (!isMac) {
            tdContext.textContent = entry.location_label || '\u2014';
            tdContext.style.color = '#6B7280';
        }

        tr.append(tdTime, tdDevice, tdActivity, tdContext);
        tr.onclick = () => openSummaryModal(entry.id);
        logsBody.appendChild(tr);
    });
}

// ── Analytics ──
async function fetchAnalytics() {
    try {
        const res = await fetch(`${API}/api/analytics/today`);
        const data = await res.json();
        renderAnalytics(data);
        renderStats(data);
    } catch { }
}

function renderStats(data) {
    const h = Math.floor(data.total_active_minutes / 60);
    const m = data.total_active_minutes % 60;
    document.getElementById('stat-active').textContent = `${h}h ${m}m`;
    document.getElementById('stat-productive').textContent = `${data.productive_pct}%`;
    document.getElementById('stat-steps').textContent = data.steps_today.toLocaleString();
    document.getElementById('stat-llm').textContent = `${data.llm_used}/${data.llm_cap}`;
}

function renderAnalytics(data) {
    const chart = document.getElementById('analytics-chart');
    const cats = data.category_minutes || {};
    const entries = Object.entries(cats).sort((a, b) => b[1] - a[1]);

    if (!entries.length) {
        chart.innerHTML = '<p class="empty-state">Collecting data...</p>';
        return;
    }

    const maxMin = Math.max(...entries.map(e => e[1]), 1);
    chart.innerHTML = entries.map(([cat, mins]) => {
        const pct = Math.max(2, (mins / maxMin) * 100);
        const color = CAT_COLORS[cat] || '#9CA3AF';
        const label = cat.replace('_', ' ');
        const h = Math.floor(mins / 60);
        const m = Math.round(mins % 60);
        const timeStr = h > 0 ? `${h}h ${m}m` : `${m}m`;
        return `<div class="chart-bar-row">
            <span class="chart-label">${esc(label)}</span>
            <div class="chart-bar-track">
                <div class="chart-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <span class="chart-bar-time">${timeStr}</span>
        </div>`;
    }).join('');
}

// ── Category Inference from App Names ──
function inferCategory(appName, windowTitle) {
    const text = `${appName} ${windowTitle}`.toLowerCase();
    const keywords = {
        studying: ['notion', 'anki', 'pdf', 'lecture', 'coursera', 'udemy', 'research', 'textbook', 'academia'],
        working: ['vscode', 'xcode', 'terminal', 'github', 'linear', 'jira', 'slack', 'gmail', 'outlook'],
        creative: ['figma', 'photoshop', 'blender', 'premiere', 'after effects', 'adobe', 'procreate', 'illustrator'],
        entertainment: ['netflix', 'youtube', 'reddit', 'tiktok', 'twitch', 'gaming', 'steam', 'epic', 'game'],
        social_media: ['twitter', 'instagram', 'facebook', 'linkedin', 'discord', 'telegram', 'whatsapp'],
        gaming: ['league', 'valorant', 'cs:go', 'minecraft', 'fortnite', 'genshin', 'roblox', 'game'],
        break: ['spotify', 'apple music', 'coffee', 'news', 'hacker news'],
    };
    for (const [cat, kws] of Object.entries(keywords)) {
        if (kws.some(kw => text.includes(kw))) return cat;
    }
    return 'unknown';
}

// ── Hourly Summaries (Enhanced) ──
let allLogsCache = [];
async function triggerHourlyRecap() {
    const btn = document.getElementById('trigger-recap-btn');
    if (btn) { btn.textContent = 'Generating…'; btn.disabled = true; }
    try {
        await fetch(`${API}/api/trigger-hourly-summary`, { method: 'POST' });
        await fetchHourlySummaries();
    } catch { }
    if (btn) { btn.textContent = 'Generate Now'; btn.disabled = false; }
}

// Words to ignore when extracting keywords from window titles
const TITLE_STOPWORDS = new Set([
    'the','and','for','with','from','this','that','you','are','was','has',
    'have','been','will','not','but','your','all','new','how','can','more',
    'its','our','one','com','www','http','https','app','tab','window',
    'untitled','document','file','page','home','edit','view','help','menu',
]);

function extractTitleKeywords(logs) {
    const wordCounts = {};
    logs.forEach(log => {
        const title = (log.window_title || '').toLowerCase();
        // Split on common separators: -, |, ·, :, /
        const parts = title.split(/[-|·:\/–—]+/);
        parts.forEach(part => {
            const words = part.trim().split(/\s+/);
            words.forEach(w => {
                const clean = w.replace(/[^a-z0-9+#]/g, '');
                if (clean.length >= 3 && !TITLE_STOPWORDS.has(clean)) {
                    wordCounts[clean] = (wordCounts[clean] || 0) + 1;
                }
            });
        });
    });
    return Object.entries(wordCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([w]) => w);
}

function buildLiveHourCard(nowLogs) {
    if (!nowLogs.length) return '';

    const now = new Date();
    const hourStart = new Date(now);
    hourStart.setMinutes(0, 0, 0);
    const hourEnd = new Date(hourStart.getTime() + 3600000);

    const dateStr = now.toLocaleDateString([], { month: 'short', day: 'numeric', timeZone: uiTimezone });
    const timeStr = hourStart.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: uiTimezone });
    const endTimeStr = hourEnd.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: uiTimezone });

    // Top apps
    const appCounts = {};
    nowLogs.forEach(log => {
        const app = log.app_name || 'unknown';
        appCounts[app] = (appCounts[app] || 0) + 1;
    });
    const topApps = Object.entries(appCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([app]) => app);

    // Title keywords (exclude app names to avoid redundancy)
    const appSet = new Set(topApps.map(a => a.toLowerCase().replace(/[^a-z0-9]/g, '')));
    const titleWords = extractTitleKeywords(nowLogs).filter(w => !appSet.has(w));

    const allKeywords = [...topApps, ...titleWords].slice(0, 8);
    if (!allKeywords.length) return '';

    const chips = allKeywords.map(k =>
        `<span style="padding:2px 10px;background:#F3F4F6;border:1px solid #E5E7EB;border-radius:12px;font-size:12px;color:#374151;">${esc(k)}</span>`
    ).join('');

    const minutesIn = Math.floor((now - hourStart) / 60000);

    return `<div class="summary-card" style="border:1px solid #C7D2FE;background:#EEF2FF;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <span class="summary-time">${esc(dateStr)}, ${esc(timeStr)} — ${esc(endTimeStr)}</span>
            <span style="display:flex;align-items:center;gap:6px;font-size:11px;color:#4F46E5;font-weight:600;">
                <span style="width:6px;height:6px;border-radius:50%;background:#4F46E5;display:inline-block;animation:pulse 2s infinite;"></span>
                ${minutesIn}m in
            </span>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">${chips}</div>
        <p style="margin-top:8px;font-size:11px;color:#6B7280;">Summary generates at ${esc(endTimeStr)}</p>
    </div>`;
}

async function fetchHourlySummaries() {
    try {
        const res = await fetch(`${API}/api/hourly-summaries?limit=8`);
        const data = await res.json();
        const list = document.getElementById('summaries-list');

        // Always fetch fresh logs for the live card + app breakdown
        try {
            const logsRes = await fetch(`${API}/api/logs?limit=300`);
            allLogsCache = await logsRes.json();
        } catch { }

        // Build live current-hour card from logs (no AI needed)
        const nowHourKey = localHourKey(new Date());
        const nowLogs = allLogsCache.filter(log => {
            if (log.device !== 'mac') return false;
            return localHourKey(log.timestamp) === nowHourKey;
        });

        // Check if a completed summary already exists for the current hour
        const hasCompletedSummary = data.some(s => {
            const source = s.hour_start_local || s.hour_start_utc || s.hour_start;
            return localHourKey(source) === nowHourKey;
        });

        const liveCard = (!hasCompletedSummary) ? buildLiveHourCard(nowLogs) : '';

        if (!data.length && !liveCard) {
            list.innerHTML = '<p class="empty-state">No activity this hour yet.</p>';
            return;
        }

        const completedCards = data.map(s => {
            const source = s.hour_start_local || s.hour_start_utc || s.hour_start;
            const date = parseServerTimestamp(source);
            if (!date) return '';
            const endDate = new Date(date.getTime() + 3600000);
            const dateStr = date.toLocaleDateString([], { month: 'short', day: 'numeric', timeZone: uiTimezone });
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: uiTimezone });
            const endTimeStr = endDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: uiTimezone });
            const hourKey = localHourKey(date);

            const hourLogs = allLogsCache.filter(log => {
                return log.device === 'mac' && localHourKey(log.timestamp) === hourKey;
            });
            const appCounts = {};
            hourLogs.forEach(log => {
                appCounts[log.app_name || 'unknown'] = (appCounts[log.app_name || 'unknown'] || 0) + 1;
            });
            const topApps = Object.entries(appCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 3)
                .map(([app]) => app)
                .join(', ');

            const score = s.productivity_score != null ? s.productivity_score.toFixed(1) : '\u2014';
            const scoreColor = s.productivity_score >= 7 ? '#22C55E' : s.productivity_score >= 4 ? '#F59E0B' : '#EF4444';
            return `<div class="summary-card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span class="summary-time">${esc(dateStr)}, ${esc(timeStr)} — ${esc(endTimeStr)}</span>
                    <span style="background:${scoreColor}1a;color:${scoreColor};padding:4px 8px;border-radius:4px;font-weight:600;font-size:12px;border:1px solid ${scoreColor}33;">${esc(score)}/10</span>
                </div>
                <p style="margin-bottom:8px;">${esc(s.summary_text)}</p>
                <div style="font-size:12px;color:#6B7280;display:flex;gap:6px;flex-wrap:wrap;">
                    ${topApps ? `<span style="padding:2px 8px;background:#F3F4F6;border:1px solid #E5E7EB;border-radius:4px;color:#374151;">${esc(topApps)}</span>` : ''}
                </div>
            </div>`;
        }).join('');

        list.innerHTML = liveCard + completedCards;
    } catch { }
}

// ── Calendar View (Weekly activity grid) ──
async function renderCalendar() {
    try {
        const calView = document.getElementById('calendar-view');
        if (!calView) return;

        // Fetch logs for calendar (if not already cached)
        if (allLogsCache.length === 0) {
            const logsRes = await fetch(`${API}/api/logs?limit=500`);
            allLogsCache = await logsRes.json();
        }

        // Group logs by day + hour
        const dayMap = {}; // date ISO string -> { hour -> entries }
        allLogsCache.forEach(log => {
            const logDate = parseServerTimestamp(log.timestamp);
            if (!logDate) return;
            const dateKey = localDateKey(logDate);
            const hour = localHourNumber(logDate);
            if (hour == null) return;
            if (!dayMap[dateKey]) dayMap[dateKey] = {};
            if (!dayMap[dateKey][hour]) dayMap[dateKey][hour] = [];
            dayMap[dateKey][hour].push(log);
        });

        // Build last 7 days calendar
        const days = [];
        for (let i = 6; i >= 0; i--) {
            const d = new Date();
            d.setDate(d.getDate() - i);
            days.push({
                key: localDateKey(d),
                label: d.toLocaleDateString([], { weekday: 'short', timeZone: uiTimezone }),
            });
        }

        let html = '<div style="display:grid;grid-template-columns:60px repeat(7,1fr);gap:8px;align-items:start;">';
        // Header row with day names
        html += '<div style="font-size:12px;color:#6B7280;font-weight:600;"></div>';
        days.forEach((day) => {
            html += `<div style="font-size:12px;color:#6B7280;font-weight:600;text-align:center;">${day.label}</div>`;
        });

        // Hour rows (8am-10pm)
        for (let hour = 8; hour < 22; hour++) {
            const h12 = hour % 12 || 12;
            const ampm = hour < 12 ? 'AM' : 'PM';
            const hourStr = `${h12} ${ampm}`;
            html += `<div style="font-size:11px;color:#6B7280;text-align:right;padding-right:8px;">${hourStr}</div>`;
            days.forEach(day => {
                const logs = dayMap[day.key]?.[hour] || [];
                const categories = logs.map(l => inferCategory(l.app_name || '', l.window_title || '')).filter(c => c !== 'unknown');
                const topCat = categories.length ? categories[0] : null;
                const color = topCat && CAT_COLORS[topCat] ? CAT_COLORS[topCat] : 'rgba(255,255,255,0.05)';
                const actualColor = topCat && CAT_COLORS[topCat] ? `var(${topCat === 'studying' ? '--cat-studying' : topCat === 'working' ? '--cat-working' : topCat === 'creative' ? '--cat-creative' : topCat === 'entertainment' ? '--cat-entertainment' : topCat === 'social_media' ? '--cat-social-media' : topCat === 'gaming' ? '--cat-gaming' : topCat === 'break' ? '--cat-break' : '--cat-idle'})` : 'rgba(255,255,255,0.05)';
                html += `<div style="min-height:30px;background:${actualColor}30;border:1px solid ${actualColor}40;border-radius:4px;cursor:pointer;" title="${topCat || 'inactive'}"></div>`;
            });
        }
        html += '</div>';
        calView.innerHTML = html;
    } catch (e) {
        console.error('Calendar render error:', e);
    }
}

// ── Call-Out Banner ──
const calloutBanner = document.getElementById('callout-banner');
const calloutMessage = document.getElementById('callout-message');
const calloutReply = document.getElementById('callout-reply');

async function fetchCallout() {
    try {
        const res = await fetch(`${API}/api/callout`);
        const data = await res.json();
        if (data.callout) {
            calloutMessage.textContent = data.callout;
            calloutBanner.classList.remove('hidden');
            if (data.callout !== lastCalloutNotification) {
                lastCalloutNotification = data.callout;
                maybeNotify('Vero', data.callout, 'callout');
            }
        } else {
            calloutBanner.classList.add('hidden');
            lastCalloutNotification = '';
        }
    } catch { }
}

document.getElementById('callout-submit').addEventListener('click', async () => {
    const reply = calloutReply.value.trim();
    if (!reply) return;

    // Optimistic UI update to feel responsive
    calloutBanner.classList.add('hidden');
    calloutReply.value = '';

    fetch(`${API}/api/prompt-reply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply })
    }).catch(() => { });
    fetch(`${API}/api/callout/dismiss`, { method: 'POST' }).catch(() => { });
});

document.getElementById('callout-reply').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('callout-submit').click();
});

document.getElementById('callout-dismiss').addEventListener('click', async () => {
    await fetch(`${API}/api/callout/dismiss`, { method: 'POST' });
    calloutBanner.classList.add('hidden');
    lastCalloutNotification = '';
});

// ── Tracking Toggle ──
const toggleBtn = document.getElementById('toggle-tracking-btn');
const trackingPulse = document.getElementById('tracking-pulse');
const trackingBadge = document.getElementById('tracking-badge');
let isTrackingEnabled = true;

function updateTrackingUI(enabled) {
    isTrackingEnabled = enabled;
    toggleBtn.textContent = enabled ? 'Tracking: ON' : 'Tracking: OFF';
    toggleBtn.classList.toggle('active', enabled);
    toggleBtn.classList.toggle('inactive', !enabled);
    trackingPulse.classList.toggle('inactive', !enabled);
    trackingBadge.classList.toggle('inactive', !enabled);
    trackingBadge.textContent = enabled ? 'Live' : 'Paused';
}

toggleBtn.addEventListener('click', async () => {
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
document.getElementById('interval-pills').addEventListener('click', async (e) => {
    const pill = e.target.closest('.interval-pill');
    if (!pill) return;
    const mins = parseInt(pill.dataset.val);
    document.querySelectorAll('.interval-pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    pollingSlider.value = mins;
    try {
        await fetch(`${API}/api/settings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ polling_interval_seconds: mins * 60 })
        });
    } catch { }
});

// ── Modal ──
const modalOverlay = document.getElementById('summary-modal');
const summaryText = document.getElementById('summary-text');

async function openSummaryModal(logId) {
    modalOverlay.classList.remove('hidden');
    summaryText.textContent = 'Generating AI insight...';
    try {
        const res = await fetch(`${API}/api/summary/${logId}`);
        if (res.ok) {
            const data = await res.json();
            const text = data.summary_text || data.summary || 'Could not generate summary.';
            const focus = data.focus_assessment ? `\nFocus: ${data.focus_assessment}` : '';
            const confidence = typeof data.confidence === 'number' ? ` (${Math.round(data.confidence * 100)}% confidence)` : '';
            const signals = Array.isArray(data.signals) && data.signals.length
                ? `\nSignals: ${data.signals.join(' · ')}`
                : '';
            summaryText.textContent = `${text}${focus}${confidence}${signals}`;
        } else {
            summaryText.textContent = 'Could not generate summary.';
        }
    } catch {
        summaryText.textContent = 'Error connecting to AI.';
    }
}

document.getElementById('close-modal-btn').addEventListener('click', () => modalOverlay.classList.add('hidden'));
modalOverlay.addEventListener('click', (e) => { if (e.target === modalOverlay) modalOverlay.classList.add('hidden'); });

// ── Settings Drawer ──
const TIMEZONES = [
    'America/Los_Angeles', 'America/Denver', 'America/Chicago', 'America/New_York',
    'America/Sao_Paulo', 'Europe/London', 'Europe/Paris', 'Europe/Berlin',
    'Asia/Dubai', 'Asia/Kolkata', 'Asia/Shanghai', 'Asia/Tokyo',
    'Australia/Sydney', 'Pacific/Auckland',
];

function populateTimezones() {
    const sel = document.getElementById('setting-timezone');
    TIMEZONES.forEach(tz => {
        const opt = document.createElement('option');
        opt.value = tz;
        opt.textContent = tz.replace('_', ' ');
        sel.appendChild(opt);
    });
    // Try to detect user's timezone
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (detected && !TIMEZONES.includes(detected)) {
        const opt = document.createElement('option');
        opt.value = detected;
        opt.textContent = detected.replace('_', ' ');
        sel.insertBefore(opt, sel.firstChild);
    }
    sel.value = detected || 'America/Los_Angeles';
}

function openSettings() {
    document.getElementById('settings-drawer').classList.remove('hidden');
    document.getElementById('settings-backdrop').classList.remove('hidden');
    loadSettings();
}

function closeSettings() {
    document.getElementById('settings-drawer').classList.add('hidden');
    document.getElementById('settings-backdrop').classList.add('hidden');
}

function updateNotificationPermissionUI() {
    const statusEl = document.getElementById('notification-status');
    const btn = document.getElementById('enable-notifications-btn');
    if (!statusEl || !btn) return;
    if (!('Notification' in window)) {
        statusEl.textContent = 'Unsupported';
        btn.disabled = true;
        btn.textContent = 'Unavailable';
        return;
    }
    const perm = Notification.permission;
    if (perm === 'granted') {
        statusEl.textContent = 'Enabled';
        statusEl.style.color = '#16A34A';
        btn.textContent = 'Enabled';
        btn.disabled = true;
    } else if (perm === 'denied') {
        statusEl.textContent = 'Blocked in browser';
        statusEl.style.color = '#D97706';
        btn.textContent = 'Blocked';
        btn.disabled = true;
    } else {
        statusEl.textContent = 'Not enabled';
        statusEl.style.color = '#6B7280';
        btn.textContent = 'Enable';
        btn.disabled = false;
    }
}

async function requestNotifications() {
    if (!('Notification' in window)) return;
    try {
        await Notification.requestPermission();
    } catch { }
    updateNotificationPermissionUI();
}

function renderZones(zones) {
    const list = document.getElementById('zones-list');
    if (!list) return;
    if (!zones.length) {
        list.innerHTML = '<p class="settings-note">No zones configured.</p>';
        return;
    }
    list.innerHTML = zones.map((zone) => {
        const urls = zoneAutomationUrls(zone.slug || zone.name || '');
        return `
        <div class="zone-editor" data-zone-id="${zone.id || ''}" data-is-default="${zone.is_default ? 'true' : 'false'}">
            <div class="zone-editor-row">
                <input class="setting-input zone-name" value="${escAttr(zone.name || '')}" placeholder="Zone name" />
                <input class="setting-input zone-radius" type="number" min="25" max="500" value="${zone.radius_meters || 75}" />
                <select class="zone-type">
                    ${['home', 'lecture', 'study', 'gym', 'custom'].map((opt) => `<option value="${opt}" ${zone.zone_type === opt ? 'selected' : ''}>${opt}</option>`).join('')}
                </select>
            </div>
            <div class="zone-editor-row">
                <input class="setting-input zone-slug" value="${escAttr(zone.slug || '')}" placeholder="slug" ${zone.is_default ? 'readonly' : ''} />
                <input class="setting-input zone-focus" value="${escAttr(zone.focus_mode || '')}" placeholder="Focus hint" />
                <select class="zone-enabled">
                    <option value="true" ${zone.enabled ? 'selected' : ''}>Enabled</option>
                    <option value="false" ${!zone.enabled ? 'selected' : ''}>Disabled</option>
                </select>
            </div>
            <div class="settings-note zone-slug-preview">Slug preview: ${esc(zone.slug || slugify(zone.name || '')) || 'required'}</div>
            <div class="zone-automation-urls">
                <div class="zone-url-line" data-kind="arrive">
                    <span>${esc(urls.arrive)}</span>
                    <button class="setting-action-btn zone-copy-url-btn" type="button" data-url="${escAttr(urls.arrive)}">Copy Arrive URL</button>
                </div>
                <div class="zone-url-line" data-kind="leave">
                    <span>${esc(urls.leave)}</span>
                    <button class="setting-action-btn zone-copy-url-btn" type="button" data-url="${escAttr(urls.leave)}">Copy Leave URL</button>
                </div>
            </div>
            <div class="settings-note zone-error" style="color:#B91C1C;display:none;"></div>
            <div class="zone-editor-actions">
                <button class="setting-action-btn zone-save-btn" type="button">Save</button>
                ${zone.is_default ? '<span class="settings-note" style="margin:0;">Default zone</span>' : '<button class="setting-action-btn zone-delete-btn" type="button">Delete</button>'}
            </div>
        </div>
    `;
    }).join('');

    list.querySelectorAll('.zone-editor').forEach((editor) => {
        const nameInput = editor.querySelector('.zone-name');
        const slugInput = editor.querySelector('.zone-slug');
        const preview = editor.querySelector('.zone-slug-preview');
        const arriveText = editor.querySelector('.zone-url-line[data-kind="arrive"] span');
        const leaveText = editor.querySelector('.zone-url-line[data-kind="leave"] span');
        const arriveBtn = editor.querySelector('.zone-url-line[data-kind="arrive"] .zone-copy-url-btn');
        const leaveBtn = editor.querySelector('.zone-url-line[data-kind="leave"] .zone-copy-url-btn');
        const isDefault = editor.dataset.isDefault === 'true';
        const refreshUrls = () => {
            const dynamicSlug = slugify(slugInput.value || nameInput.value);
            const urls = zoneAutomationUrls(dynamicSlug);
            if (arriveText) arriveText.textContent = urls.arrive;
            if (leaveText) leaveText.textContent = urls.leave;
            if (arriveBtn) arriveBtn.dataset.url = urls.arrive;
            if (leaveBtn) leaveBtn.dataset.url = urls.leave;
        };
        const syncPreview = () => {
            const currentSlug = slugify(slugInput.value || nameInput.value);
            if (!isDefault && !slugInput.value.trim() && nameInput.value.trim()) {
                slugInput.value = currentSlug;
            }
            preview.textContent = `Slug preview: ${slugify(slugInput.value || nameInput.value) || 'required'}`;
            refreshUrls();
        };
        nameInput?.addEventListener('input', syncPreview);
        slugInput?.addEventListener('input', syncPreview);
        refreshUrls();
    });

    list.querySelectorAll('.zone-save-btn').forEach((btn) => btn.addEventListener('click', async () => {
        const editor = btn.closest('.zone-editor');
        const errorEl = editor.querySelector('.zone-error');
        const name = editor.querySelector('.zone-name').value.trim();
        const rawSlug = editor.querySelector('.zone-slug').value.trim();
        const slug = slugify(rawSlug || name);
        if (!name) {
            errorEl.textContent = 'Zone name is required.';
            errorEl.style.display = 'block';
            return;
        }
        if (!slug || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
            errorEl.textContent = 'Slug must use lowercase letters, numbers, and hyphens.';
            errorEl.style.display = 'block';
            return;
        }
        errorEl.style.display = 'none';
        const payload = {
            name,
            radius_meters: parseInt(editor.querySelector('.zone-radius').value || '75', 10),
            zone_type: editor.querySelector('.zone-type').value,
            slug,
            focus_mode: editor.querySelector('.zone-focus').value.trim(),
            enabled: editor.querySelector('.zone-enabled').value === 'true',
        };
        const zoneId = editor.dataset.zoneId;
        const url = zoneId ? `${API}/api/zones/${zoneId}` : `${API}/api/zones`;
        const method = zoneId ? 'PATCH' : 'POST';
        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (res.ok) {
                loadZones();
                return;
            }
            const err = await res.json().catch(() => ({}));
            errorEl.textContent = err?.detail?.message || err.detail || 'Could not save zone.';
            errorEl.style.display = 'block';
        } catch {
            errorEl.textContent = 'Network error while saving zone.';
            errorEl.style.display = 'block';
        }
    }));

    list.querySelectorAll('.zone-delete-btn').forEach((btn) => btn.addEventListener('click', async () => {
        const editor = btn.closest('.zone-editor');
        const zoneId = editor.dataset.zoneId;
        if (!zoneId) {
            editor.remove();
            return;
        }
        try {
            const res = await fetch(`${API}/api/zones/${zoneId}`, { method: 'DELETE' });
            if (res.ok) loadZones();
        } catch { }
    }));

    list.querySelectorAll('.zone-copy-url-btn').forEach((btn) => btn.addEventListener('click', async () => {
        const original = btn.textContent;
        const url = btn.dataset.url || '';
        if (!url) return;
        try {
            await navigator.clipboard.writeText(url);
            btn.textContent = 'Copied';
            setTimeout(() => { btn.textContent = original; }, 1000);
        } catch {
            btn.textContent = 'Copy failed';
            setTimeout(() => { btn.textContent = original; }, 1200);
        }
    }));
}

async function loadZones() {
    const list = document.getElementById('zones-list');
    if (!list) return;
    try {
        const res = await fetch(`${API}/api/zones`);
        if (!res.ok) throw new Error('zones');
        const data = await res.json();
        renderZones(data.zones || []);
    } catch {
        list.innerHTML = '<p class="settings-note">Could not load zones.</p>';
    }
}

function addZoneDraft() {
    const list = document.getElementById('zones-list');
    if (!list) return;
    const existing = Array.from(list.querySelectorAll('.zone-editor')).map((el) => ({
        id: el.dataset.zoneId ? parseInt(el.dataset.zoneId, 10) : null,
        is_default: el.dataset.isDefault === 'true',
        name: el.querySelector('.zone-name')?.value || '',
        radius_meters: parseInt(el.querySelector('.zone-radius')?.value || '75', 10),
        zone_type: el.querySelector('.zone-type')?.value || 'custom',
        slug: el.querySelector('.zone-slug')?.value || '',
        focus_mode: el.querySelector('.zone-focus')?.value || '',
        enabled: (el.querySelector('.zone-enabled')?.value || 'true') === 'true',
    }));
    existing.push({
        id: null,
        is_default: false,
        name: '',
        radius_meters: 75,
        zone_type: 'custom',
        slug: '',
        focus_mode: '',
        enabled: true,
    });
    renderZones(existing);
}

async function loadSettings() {
    try {
        const res = await fetch(`${API}/api/settings`);
        const s = await res.json();
        document.getElementById('setting-tracking').checked = s.tracking_enabled;
        document.getElementById('setting-polling').value = String(s.polling_interval_seconds);
        document.getElementById('setting-ai-provider').value = s.ai_provider || 'auto';
        document.getElementById('setting-llm-mode').value = s.llm_mode;
        document.getElementById('setting-llm-cap').value = s.llm_daily_cap;
        document.getElementById('setting-class-interval').value = String(s.classification_interval_seconds);
        document.getElementById('setting-hourly').checked = s.hourly_summaries_enabled;
        if (s.user_timezone) {
            document.getElementById('setting-timezone').value = s.user_timezone;
            uiTimezone = s.user_timezone;
        }
        updateNotificationPermissionUI();
        loadZones();
        // Health check
        const hRes = await fetch(`${API}/api/healthz`);
        if (hRes.ok) {
            const h = await hRes.json();
            document.getElementById('setting-health').textContent = h.status === 'ok' ? 'Healthy' : h.status;
            document.getElementById('setting-health').style.color = h.status === 'ok' ? '#16A34A' : '#D97706';
        }
    } catch { }
}

document.getElementById('settings-save-btn').addEventListener('click', async () => {
    const payload = {
        tracking_enabled: document.getElementById('setting-tracking').checked,
        polling_interval_seconds: parseInt(document.getElementById('setting-polling').value),
        ai_provider: document.getElementById('setting-ai-provider').value,
        llm_mode: document.getElementById('setting-llm-mode').value,
        llm_daily_cap: parseInt(document.getElementById('setting-llm-cap').value),
        classification_interval_seconds: parseInt(document.getElementById('setting-class-interval').value),
        hourly_summaries_enabled: document.getElementById('setting-hourly').checked,
        user_timezone: document.getElementById('setting-timezone').value,
    };
    try {
        await fetch(`${API}/api/settings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        updateTrackingUI(payload.tracking_enabled);
        pollingSlider.value = Math.max(1, Math.floor(payload.polling_interval_seconds / 60));
        pollingLabel.textContent = `Every ${pollingSlider.value}m`;
        closeSettings();
    } catch { }
});

document.getElementById('settings-btn').addEventListener('click', openSettings);
document.getElementById('enable-notifications-btn').addEventListener('click', requestNotifications);
document.getElementById('add-zone-btn').addEventListener('click', addZoneDraft);
const ONBOARDING_KEY = 'vero_onboarded_v2';

if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
        await Promise.allSettled([
            fetchData(true),
            fetchAnalytics(),
            fetchHourlySummaries(),
            fetchControlCenterStatus(),
            renderCalendar(),
        ]);
    });
}

const rerunOnboardingBtn = document.getElementById('rerun-onboarding-btn');
if (rerunOnboardingBtn) {
    rerunOnboardingBtn.addEventListener('click', () => {
        localStorage.removeItem(ONBOARDING_KEY);
        checkOnboarding();
    });
}

// ── Onboarding ──
async function checkOnboarding() {
    try {
        const res = await fetch(`${API}/api/state`);
        const states = await res.json();
        // Show onboarding
        document.getElementById('onboarding-overlay').classList.remove('hidden');
        // Check mac status
        const macOk = states.mac_online === true;
        const macStatusEl = document.getElementById('onboard-mac-status');
        if (macOk) {
            macStatusEl.innerHTML = '&#10003; The hidden Mac agent is connected and sending data.';
        } else {
            const launchHref = states.mac_launch_url || 'vero://open';
            macStatusEl.innerHTML = `The hidden Mac agent is not connected. <a href="${launchHref}" style="color:#58a6ff;text-decoration:underline;">Open Vero</a> or <a href="/setup/mac" target="_blank" style="color:#58a6ff;text-decoration:underline;">Install / Repair &rarr;</a>`;
        }
        // Check iOS shortcut status
        try {
            const iosRes = await fetch(`${API}/api/ios-setup-status`);
            if (iosRes.ok) {
                const iosData = await iosRes.json();
                const required = iosData.required || iosData.checklist || [];
                const configured = required.filter(item => item.configured).length;
                const total = required.length;
                const iosStatusEl = document.getElementById('onboard-ios-status');
                if (iosStatusEl) {
                    if (configured === total && total > 0) {
                        iosStatusEl.innerHTML = `&#10003; Required iPhone automations configured.`;
                    } else if (configured > 0) {
                        iosStatusEl.innerHTML = `${configured}/${total} required automations configured.`;
                    }
                }
            }
        } catch { }
        // Detect timezone
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        document.getElementById('onboard-tz').textContent = tz || 'America/Los_Angeles';
    } catch { }
}

function nextOnboardStep(step) {
    document.querySelectorAll('.onboarding-step').forEach(s => s.classList.add('hidden'));
    document.getElementById(`onboard-step-${step}`).classList.remove('hidden');
}

async function completeOnboarding() {
    document.getElementById('onboarding-overlay').classList.add('hidden');
    const tz = document.getElementById('onboard-tz').textContent;
    try {
        await fetch(`${API}/api/settings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_timezone: tz })
        });
        // Mark onboarding done by setting state (we'll use the prompt-reply endpoint as a workaround)
        // Actually, let's just not show it again after first visit using localStorage
    } catch { }
    localStorage.setItem(ONBOARDING_KEY, '1');
}

// ── Mobile view switching ──
function switchView(view) {
    if (view === 'settings') {
        document.querySelectorAll('.mobile-nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
        openSettings();
        return;
    }
    closeSettings();
    document.querySelectorAll('.mobile-nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    const sections = document.querySelectorAll('.mobile-view-section');
    if (!sections.length || window.innerWidth > 768) return;
    sections.forEach((section) => {
        section.classList.toggle('hidden', section.dataset.view !== view);
    });
}

// ── Initial fetch settings for slider sync ──
async function initSettings() {
    try {
        const res = await fetch(`${API}/api/settings`);
        const data = await res.json();
        const mins = Math.max(1, Math.floor(data.polling_interval_seconds / 60));
        pollingSlider.value = mins;
        // Sync interval pills
        document.querySelectorAll('.interval-pill').forEach(p => {
            p.classList.toggle('active', parseInt(p.dataset.val) === mins);
        });
        if (data.tracking_enabled !== undefined) updateTrackingUI(data.tracking_enabled);
    } catch { }
}

// ── Chat Bar ──
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send');
const chatReplyEl = document.getElementById('chat-reply');
const chatReplyText = document.getElementById('chat-reply-text');
const chatHistoryList = document.getElementById('chat-history-list');
let lastCheckinNotification = '';
let lastCalloutNotification = '';
let lastChatNotification = '';

function maybeNotify(title, body, kind) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
        Notification.requestPermission();
        return;
    }
    if (Notification.permission !== 'granted') return;
    if (kind === 'checkin' && body === lastCheckinNotification) return;
    if (kind === 'callout' && body === lastCalloutNotification) return;
    if (kind === 'chat' && body === lastChatNotification) return;
    new Notification(title, { body });
}

async function sendChat() {
    const msg = chatInput.value.trim();
    if (!msg) return;
    chatInput.value = '';
    chatSendBtn.textContent = '...';
    chatSendBtn.disabled = true;

    try {
        const res = await fetch(`${API}/api/chat`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        if (res.ok) {
            const data = await res.json();
            chatReplyText.textContent = data.reply;
            chatReplyEl.classList.remove('hidden');
            if (data.reply && data.reply !== lastChatNotification) {
                lastChatNotification = data.reply;
                maybeNotify('Vero', data.reply, 'chat');
            }
            fetchChatHistory();
            // Auto-hide reply after 8 seconds
            setTimeout(() => chatReplyEl.classList.add('hidden'), 8000);
        }
    } catch { }
    chatSendBtn.textContent = 'Send';
    chatSendBtn.disabled = false;
}

chatSendBtn.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

async function fetchChatHistory() {
    if (!chatHistoryList) return;
    try {
        const res = await fetch(`${API}/api/chat/history`);
        if (!res.ok) throw new Error('chat-history');
        const data = await res.json();
        const messages = (data.messages || []).slice(-4).reverse();
        if (!messages.length) {
            chatHistoryList.innerHTML = '<p class="empty-state">No chat yet.</p>';
            return;
        }
        chatHistoryList.innerHTML = messages.map((turn) => `
            <div class="chat-turn">
                <div class="chat-turn-time">${esc(formatTime(turn.time) || (turn.time || ''))}</div>
                <div class="chat-turn-line"><strong>You:</strong> ${esc(turn.user || '')}</div>
                <div class="chat-turn-line"><strong>Vero:</strong> ${esc(turn.reply || '')}</div>
            </div>
        `).join('');
    } catch {
        chatHistoryList.innerHTML = '<p class="empty-state">Could not load chat history.</p>';
    }
}

// ── Check-In System ──
const checkinBanner = document.getElementById('checkin-banner');
const checkinMessage = document.getElementById('checkin-message');
const checkinConfirm = document.getElementById('checkin-confirm');
const checkinCorrection = document.getElementById('checkin-correction');
const checkinSend = document.getElementById('checkin-send');

async function fetchCheckin() {
    try {
        const res = await fetch(`${API}/api/checkin`);
        const data = await res.json();
        if (data.checkin) {
            checkinMessage.textContent = data.checkin;
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

checkinConfirm.addEventListener('click', async () => {
    // Optimistic UI hide
    checkinBanner.classList.add('hidden');
    lastCheckinNotification = '';

    fetch(`${API}/api/checkin/confirm`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true })
    }).catch(() => { });
});

checkinSend.addEventListener('click', async () => {
    const correction = checkinCorrection.value.trim();
    if (!correction) return;

    // Optimistic UI hide
    checkinBanner.classList.add('hidden');
    checkinCorrection.value = '';
    lastCheckinNotification = '';

    fetch(`${API}/api/checkin/confirm`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: false, correction })
    }).catch(() => { });
});

checkinCorrection.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') checkinSend.click();
});

// ── iOS Shortcuts Setup Check ──
async function checkIosSetupStatus() {
    try {
        const r = await fetch(`${API}/api/ios-setup-status`);
        if (!r.ok) return;
        const d = await r.json();
        const required = d.required || d.checklist || [];
        const unconfigured = required.filter(item => !item.configured);
        const cardIos = document.getElementById('card-ios');
        // Remove any existing warning
        const existing = document.getElementById('ios-setup-warning');
        if (existing) existing.remove();
        if (unconfigured.length > 0 && !d.ios_recent_ping) {
            // Show warning badge on iPhone card
            const warning = document.createElement('div');
            warning.id = 'ios-setup-warning';
            warning.style.cssText = 'margin-top:0.5rem;padding:0.4rem 0.7rem;background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;font-size:0.75rem;color:#92400E;cursor:pointer;';
            warning.innerHTML = `${unconfigured.length} required iPhone automation${unconfigured.length > 1 ? 's' : ''} missing — <u>tap to fix</u>`;
            warning.onclick = () => window.open('/setup/ios', '_blank');
            cardIos.appendChild(warning);
        }
    } catch { }
}

async function fetchControlCenterStatus() {
    try {
        const [healthRes, iosRes, calendarRes] = await Promise.all([
            fetch(`${API}/api/healthz`),
            fetch(`${API}/api/ios-setup-status`),
            fetch(`${API}/api/calendar/jobs?limit=25&status=pending`),
        ]);

        const health = healthRes.ok ? await healthRes.json() : null;
        const iosSetup = iosRes.ok ? await iosRes.json() : null;
        const calendar = calendarRes.ok ? await calendarRes.json() : { jobs: [] };

        if (serviceStatusEl && serviceDetailEl) {
            const status = health?.status || 'unknown';
            serviceStatusEl.textContent = status === 'ok' ? 'Healthy' : (status === 'degraded' ? 'Degraded' : 'Unknown');
            serviceStatusEl.style.color = status === 'ok' ? '#16A34A' : '#D97706';
            if (status === 'ok') {
                serviceDetailEl.textContent = `Railway is serving traffic. Build ${health?.build?.git_sha || 'unknown'} is live.`;
            } else {
                const startupError = (health?.startup_errors || [])[0];
                serviceDetailEl.textContent = startupError || 'The service is reachable, but startup or database checks need attention.';
            }
        }

        const pendingJobs = Array.isArray(calendar?.jobs) ? calendar.jobs.length : 0;
        if (calendarStatusEl && calendarDetailEl) {
            if (!latestStates || latestStates.mac_status === 'offline') {
                calendarStatusEl.textContent = 'Waiting for Mac';
                calendarStatusEl.style.color = '#D97706';
                calendarDetailEl.textContent = 'The Mac helper is the only calendar writer. Open Vero so it can pull queued calendar jobs.';
            } else if (pendingJobs > 0) {
                calendarStatusEl.textContent = `${pendingJobs} Queued`;
                calendarStatusEl.style.color = '#D97706';
                calendarDetailEl.textContent = 'Recommended: System Settings > Apple Account > iCloud > Calendar ON, then keep the Vero calendar under the iCloud section in Calendar.app.';
            } else {
                calendarStatusEl.textContent = 'Ready';
                calendarStatusEl.style.color = '#16A34A';
                calendarDetailEl.textContent = 'The Mac helper will write new sessions to Apple Calendar locally. For cloud sync, keep iCloud Calendar ON and the Vero calendar under iCloud.';
            }
        }

        if (iosSetupStatusEl && iosSetupDetailEl) {
            const required = iosSetup?.required || iosSetup?.checklist || [];
            const optional = iosSetup?.optional || [];
            const requiredConfigured = required.filter(item => item.configured).length;
            const optionalConfigured = optional.filter(item => item.configured).length;
            if (!required.length) {
                iosSetupStatusEl.textContent = 'Not configured';
                iosSetupStatusEl.style.color = '#D97706';
                iosSetupDetailEl.textContent = 'Set up zone Arrive + Leave automations first. Walking and charging are optional.';
            } else if (requiredConfigured === required.length) {
                iosSetupStatusEl.textContent = `${requiredConfigured}/${required.length} Required`;
                iosSetupStatusEl.style.color = '#16A34A';
                iosSetupDetailEl.textContent = `Required setup complete. Optional automations: ${optionalConfigured}/${optional.length}.`;
            } else {
                iosSetupStatusEl.textContent = `${requiredConfigured}/${required.length} Required`;
                iosSetupStatusEl.style.color = '#D97706';
                iosSetupDetailEl.textContent = 'Finish missing required zone automations in iPhone Setup.';
            }
        }

        if (nextStepStatusEl && nextStepDetailEl) {
            if (!latestStates || latestStates.mac_status === 'offline') {
                nextStepStatusEl.textContent = 'Open the Mac app';
                nextStepDetailEl.textContent = 'Install or repair the native app first. Once it runs once, the hidden login helper should stay on in the background.';
            } else if (latestStates.mac_status === 'degraded') {
                nextStepStatusEl.textContent = 'Grant permissions';
                nextStepDetailEl.textContent = 'Open Vero and finish Accessibility, Notifications, and Calendar access so the helper can classify activity and sync events.';
            } else if (pendingJobs > 0) {
                nextStepStatusEl.textContent = 'Enable iCloud Calendar';
                nextStepDetailEl.textContent = 'Turn on iCloud Calendar on your Mac, then make sure the Vero calendar sits under iCloud in Calendar.app rather than only On My Mac.';
            } else if ((iosSetup?.required || iosSetup?.checklist || []).some(item => !item.configured)) {
                nextStepStatusEl.textContent = 'Finish iPhone Setup';
                nextStepDetailEl.textContent = 'Add missing required zone automations (Arrive + Leave) from iPhone Setup.';
            } else {
                nextStepStatusEl.textContent = 'Everything is in place';
                nextStepDetailEl.textContent = 'Mac helper, calendar queueing, and required iPhone setup are all configured.';
            }
        }
    } catch {
        if (serviceStatusEl) serviceStatusEl.textContent = 'Unknown';
        if (serviceDetailEl) serviceDetailEl.textContent = 'Could not load Control Center health details.';
    }
}

// ── Setup ──
populateTimezones();
initSettings();
connectSSE();
fetchData();
fetchAnalytics();
fetchHourlySummaries();
fetchCallout();
fetchCheckin();
fetchChatHistory();
checkIosSetupStatus();
fetchControlCenterStatus();
renderCalendar();
if (window.innerWidth <= 768) switchView('dashboard');
window.addEventListener('resize', () => {
    const sections = document.querySelectorAll('.mobile-view-section');
    if (window.innerWidth > 768) {
        sections.forEach((section) => section.classList.remove('hidden'));
    }
});

if (!localStorage.getItem(ONBOARDING_KEY)) checkOnboarding();

// Polling fallback + analytics/checkin refresh
setInterval(() => {
    if (!sseConnected) fetchData();
}, 5000);
setInterval(fetchHourlySummaries, 60000);
setInterval(renderCalendar, 120000); // refresh calendar every 2 min
setInterval(fetchCallout, 60000);
setInterval(fetchAnalytics, 120000);
setInterval(fetchCheckin, 30000);
setInterval(fetchChatHistory, 60000);
setInterval(checkIosSetupStatus, 120000); // re-check every 2 min
setInterval(fetchControlCenterStatus, 60000);

// ── Service Worker ──
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/dashboard/sw.js').catch(() => { });
}
