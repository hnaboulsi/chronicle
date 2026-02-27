const API = '';

// ── Escape HTML to prevent XSS ──
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

// ── DOM refs ──
const clockEl = document.getElementById('clock');
const macStatus = document.getElementById('mac-status');
const macDetail = document.getElementById('mac-detail');
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

// ── Clock ──
function updateClock() {
    clockEl.textContent = new Date().toLocaleString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}
setInterval(updateClock, 1000);
updateClock();

// ── Category labels and colors ──
const CAT_LABELS = {
    studying: '📚 Studying', working: '💼 Working', entertainment: '🎬 Entertainment',
    social_media: '📲 Social Media', gaming: '🎮 Gaming', creative: '🎨 Creative',
    break: '☕ Break', idle: '💤 Idle', unknown: '🔍 Analyzing...',
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
        } catch {}
    };
    eventSource.onerror = () => {
        sseConnected = false;
        eventSource.close();
        // Reconnect after a short delay (server closes after 5 min to save resources)
        setTimeout(connectSSE, 3000);
    };
}

// ── Fallback polling (if SSE fails) ──
async function fetchData() {
    if (sseConnected) return;
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
    // Mac Card
    const macOnline = states.mac_online === true;
    const latestMac = logs.find(l => l.device === 'mac');
    if (!macOnline) {
        macStatus.textContent = 'Offline';
        macStatus.style.color = 'var(--danger)';
        if (states.last_mac_ping_age_seconds != null) {
            const mins = Math.max(1, Math.ceil(states.last_mac_ping_age_seconds / 60));
            macDetail.textContent = `Last seen ${mins}m ago`;
        } else {
            macDetail.textContent = 'Not connected';
        }
        macDetail.style.color = 'var(--text-tertiary)';
    } else if (latestMac) {
        macStatus.textContent = latestMac.app_name || 'Active';
        macStatus.style.color = 'var(--text-primary)';
        macDetail.textContent = latestMac.is_idle ? 'Idle > 30 min' : 'Active';
        macDetail.style.color = latestMac.is_idle ? 'var(--warning)' : 'var(--text-secondary)';
    }

    // iOS Card
    const latestIos = logs.find(l => l.device === 'ios');
    if (latestIos) {
        iosStatus.textContent = latestIos.location_label || 'Connected';
        iosStatus.style.color = 'var(--success)';
        const battStr = latestIos.battery_pct != null ? ` · 🔋${latestIos.battery_pct}%` : '';
        iosDetail.textContent = (latestIos.activity_type || 'Tracking') + battStr;
        iosDetail.style.color = 'var(--text-secondary)';
    } else {
        iosStatus.textContent = states.ios_recent_ping ? 'Connected' : 'Idle';
        iosStatus.style.color = states.ios_recent_ping ? 'var(--success)' : 'var(--text-tertiary)';
        iosDetail.textContent = states.ios_recent_ping ? 'Tracking location' : 'No pings received';
        iosDetail.style.color = 'var(--text-tertiary)';
    }

    // Focus Mode
    const isStudy = states.study_mode === 'active';
    focusStatus.textContent = isStudy ? 'Study Mode' : 'Off';
    focusStatus.style.color = isStudy ? 'var(--warning)' : 'var(--text-secondary)';
    focusDetail.textContent = isStudy ? 'Distraction alerts on' : 'Normal';

    // AI Reading
    const cat = states.current_activity_category || 'unknown';
    activityCategory.textContent = CAT_LABELS[cat] || cat;
    activitySummary.textContent = states.current_activity_summary || '\u2014';
    activityCategory.style.color = PRODUCTIVE.has(cat) ? 'var(--success)' : DISTRACTED.has(cat) ? 'var(--danger)' : 'var(--text-primary)';

    // Logs Table
    logsBody.innerHTML = '';
    logs.forEach((entry, i) => {
        const tr = document.createElement('tr');
        tr.className = 'fade-in';
        tr.style.animationDelay = `${i * 0.03}s`;

        let ts = entry.timestamp;
        if (ts && !ts.endsWith('Z')) ts += 'Z';
        const time = ts ? new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const isMac = entry.device === 'mac';

        const tdTime = document.createElement('td');
        tdTime.textContent = time;

        const tdDevice = document.createElement('td');
        tdDevice.textContent = isMac ? '💻' : '📱';

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
            tdContext.style.color = 'var(--text-secondary)';
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
    } catch {}
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
        const color = CAT_COLORS[cat] || 'var(--text-tertiary)';
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

// ── Hourly Summaries ──
async function fetchHourlySummaries() {
    try {
        const res = await fetch(`${API}/api/hourly-summaries?limit=4`);
        const data = await res.json();
        const list = document.getElementById('summaries-list');
        if (!data.length) {
            list.innerHTML = '<p class="empty-state">No summaries yet — they generate each hour.</p>';
            return;
        }
        list.innerHTML = data.map(s => {
            let ts = s.hour_start;
            if (ts && !ts.endsWith('Z')) ts += 'Z';
            const time = ts ? new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
            const score = s.productivity_score != null ? s.productivity_score.toFixed(1) : '\u2014';
            return `<div class="summary-card">
                <span class="summary-time">${esc(time)}</span>
                <span class="summary-score">${esc(score)}/10</span>
                <p>${esc(s.summary_text)}</p>
            </div>`;
        }).join('');
    } catch {}
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
        } else {
            calloutBanner.classList.add('hidden');
        }
    } catch {}
}

document.getElementById('callout-submit').addEventListener('click', async () => {
    const reply = calloutReply.value.trim();
    if (!reply) return;
    await fetch(`${API}/api/prompt-reply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply })
    });
    await fetch(`${API}/api/callout/dismiss`, { method: 'POST' });
    calloutBanner.classList.add('hidden');
    calloutReply.value = '';
});

document.getElementById('callout-dismiss').addEventListener('click', async () => {
    await fetch(`${API}/api/callout/dismiss`, { method: 'POST' });
    calloutBanner.classList.add('hidden');
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
    } catch {}
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
    } catch {}
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
            summaryText.textContent = data.summary;
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
    // Reset mobile nav
    document.querySelectorAll('.mobile-nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === 'dashboard'));
}

async function loadSettings() {
    try {
        const res = await fetch(`${API}/api/settings`);
        const s = await res.json();
        document.getElementById('setting-tracking').checked = s.tracking_enabled;
        document.getElementById('setting-polling').value = String(s.polling_interval_seconds);
        document.getElementById('setting-llm-mode').value = s.llm_mode;
        document.getElementById('setting-llm-cap').value = s.llm_daily_cap;
        document.getElementById('setting-class-interval').value = String(s.classification_interval_seconds);
        document.getElementById('setting-hourly').checked = s.hourly_summaries_enabled;
        if (s.user_timezone) document.getElementById('setting-timezone').value = s.user_timezone;
        // Health check
        const hRes = await fetch(`${API}/api/healthz`);
        if (hRes.ok) {
            const h = await hRes.json();
            document.getElementById('setting-health').textContent = h.status === 'ok' ? 'Healthy' : h.status;
            document.getElementById('setting-health').style.color = h.status === 'ok' ? 'var(--success)' : 'var(--warning)';
        }
    } catch {}
}

document.getElementById('settings-save-btn').addEventListener('click', async () => {
    const payload = {
        tracking_enabled: document.getElementById('setting-tracking').checked,
        polling_interval_seconds: parseInt(document.getElementById('setting-polling').value),
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
    } catch {}
});

document.getElementById('settings-btn').addEventListener('click', openSettings);

// ── Onboarding ──
async function checkOnboarding() {
    try {
        const res = await fetch(`${API}/api/state`);
        const states = await res.json();
        if (states.onboarding_complete === 'true') return;
        // Show onboarding
        document.getElementById('onboarding-overlay').classList.remove('hidden');
        // Check mac status
        const macOk = states.mac_online === true;
        document.getElementById('onboard-mac-status').textContent = macOk
            ? 'Mac tracker is connected and sending data.'
            : 'Mac tracker not detected. Install it from the setup guide.';
        // Detect timezone
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        document.getElementById('onboard-tz').textContent = tz || 'America/Los_Angeles';
    } catch {}
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
    } catch {}
    localStorage.setItem('lm_onboarded', '1');
}

// ── Mobile view switching ──
function switchView(view) {
    document.querySelectorAll('.mobile-nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    // Settings is handled by openSettings()
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
    } catch {}
}

// ── Chat Bar ──
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send');
const chatReplyEl = document.getElementById('chat-reply');
const chatReplyText = document.getElementById('chat-reply-text');

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
            // Auto-hide reply after 8 seconds
            setTimeout(() => chatReplyEl.classList.add('hidden'), 8000);
        }
    } catch {}
    chatSendBtn.textContent = 'Send';
    chatSendBtn.disabled = false;
}

chatSendBtn.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

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
            // Request notification permission if we haven't
            if ('Notification' in window && Notification.permission === 'default') {
                Notification.requestPermission();
            }
            // Show browser notification
            if ('Notification' in window && Notification.permission === 'granted') {
                new Notification('Life Manager', { body: data.checkin, icon: '🧠' });
            }
        } else {
            checkinBanner.classList.add('hidden');
        }
    } catch {}
}

checkinConfirm.addEventListener('click', async () => {
    try {
        await fetch(`${API}/api/checkin/confirm`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed: true })
        });
    } catch {}
    checkinBanner.classList.add('hidden');
});

checkinSend.addEventListener('click', async () => {
    const correction = checkinCorrection.value.trim();
    if (!correction) return;
    try {
        await fetch(`${API}/api/checkin/confirm`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed: false, correction })
        });
    } catch {}
    checkinBanner.classList.add('hidden');
    checkinCorrection.value = '';
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
        const unconfigured = (d.checklist || []).filter(item => !item.configured);
        const cardIos = document.getElementById('card-ios');
        // Remove any existing warning
        const existing = document.getElementById('ios-setup-warning');
        if (existing) existing.remove();
        if (unconfigured.length > 0 && !d.ios_recent_ping) {
            // Show warning badge on iPhone card
            const warning = document.createElement('div');
            warning.id = 'ios-setup-warning';
            warning.style.cssText = 'margin-top:0.5rem;padding:0.4rem 0.7rem;background:rgba(210,153,34,0.15);border:1px solid rgba(210,153,34,0.4);border-radius:8px;font-size:0.75rem;color:#d29922;cursor:pointer;';
            warning.innerHTML = `⚠ ${unconfigured.length} shortcut${unconfigured.length > 1 ? 's' : ''} not set up — <u>tap to fix</u>`;
            warning.onclick = () => window.open('/setup/ios', '_blank');
            cardIos.appendChild(warning);
        }
    } catch {}
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
checkIosSetupStatus();

if (!localStorage.getItem('lm_onboarded')) checkOnboarding();

// Polling fallback + analytics/checkin refresh
setInterval(() => {
    if (!sseConnected) fetchData();
    fetchHourlySummaries();
}, 5000);
setInterval(fetchCallout, 30000);
setInterval(fetchAnalytics, 30000);
setInterval(fetchCheckin, 15000);
setInterval(checkIosSetupStatus, 120000); // re-check every 2 min

// ── Service Worker ──
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/dashboard/sw.js').catch(() => {});
}
