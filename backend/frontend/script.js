const API_BASE = '';

// DOM Elements
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

// Update Local Clock
function updateClock() {
    const now = new Date();
    clockEl.innerText = now.toLocaleString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}
setInterval(updateClock, 1000);
updateClock();

// Fetch Data
async function fetchData() {
    try {
        // Fetch logs
        const logsRes = await fetch(`${API_BASE}/api/logs?limit=15`);
        const logs = await logsRes.json();

        // Fetch states
        const stateRes = await fetch(`${API_BASE}/api/state`);
        const states = await stateRes.json();

        updateUI(logs, states);
    } catch (err) {
        console.error("Error fetching data:", err);
    }
}

function updateUI(logs, states) {
    // 1. Update Mac Card (Find latest Mac log)
    const latestMac = logs.find(l => l.device === 'mac');
    if (latestMac) {
        macStatus.innerText = latestMac.app_name || 'Unknown App';
        macDetail.innerText = latestMac.is_idle ? "⚠️ Idle > 30 mins" : "Active";
        if (latestMac.is_idle) macDetail.style.color = "var(--warning)";
        else macDetail.style.color = "var(--text-secondary)";
    }

    // 2. Update iOS Card
    const latestIos = logs.find(l => l.device === 'ios');
    if (latestIos) {
        iosStatus.innerText = latestIos.location_label || 'Tracking...';
        iosDetail.innerText = latestIos.activity_type || 'Unknown Activity';
    } else {
        iosStatus.innerText = states.is_walking === "true" ? "Walking" : "Idle";
    }

    // 3. Update Focus Mode
    const isStudyMode = states.study_mode === "active";
    focusStatus.innerText = isStudyMode ? "Active" : "Inactive";
    focusStatus.style.color = isStudyMode ? "var(--warning)" : "var(--text-primary)";
    focusDetail.innerText = isStudyMode ? "Notifications Silenced" : "Normal mode";

    // 4. Update AI Reading card
    const categoryLabels = {
        studying: "📚 Studying",
        working: "💼 Working",
        entertainment: "🎬 Entertainment",
        social_media: "📲 Social Media",
        gaming: "🎮 Gaming",
        creative: "🎨 Creative",
        break: "☕ Break",
        idle: "💤 Idle",
        unknown: "🔍 Analyzing...",
    };
    const cat = states.current_activity_category || "unknown";
    activityCategory.innerText = categoryLabels[cat] || cat;
    activitySummary.innerText = states.current_activity_summary || "—";
    const isProductive = ["studying", "working", "creative"].includes(cat);
    const isDistracted = ["entertainment", "social_media", "gaming"].includes(cat);
    activityCategory.style.color = isProductive ? "var(--success)" : isDistracted ? "var(--danger)" : "var(--text-primary)";

    // 5. Update Logs Table
    logsBody.innerHTML = '';
    logs.forEach((log, index) => {
        const tr = document.createElement('tr');
        tr.className = 'fade-in';
        tr.style.animationDelay = `${index * 0.05}s`;

        let timestampStr = log.timestamp;
        if (!timestampStr.endsWith('Z')) timestampStr += 'Z';
        const time = new Date(timestampStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const isMac = log.device === 'mac';

        let activityText = "";
        let contextText = "";

        if (isMac) {  // eslint-disable-line
            activityText = log.app_name;
            // Safari/Chrome now send "Tab Name - URL"
            let titleText = log.window_title;
            if (titleText) {
                // Formatting
                if (titleText.length > 55) titleText = titleText.substring(0, 55) + "...";
                contextText = `<span class="tab-pill">${titleText}</span>`;
            } else {
                contextText = `<span style="color:var(--text-secondary)">No active tab</span>`;
            }
        } else {
            activityText = log.activity_type || "Location Ping";
            contextText = `<span style="color:var(--text-secondary)">${log.location_label || "-"}</span>`;
        }

        tr.innerHTML = `
            <td>${time}</td>
            <td>${isMac ? '💻 Mac' : '📱 iOS'}</td>
            <td>${activityText}</td>
            <td>${contextText}</td>
        `;

        tr.onclick = () => openSummaryModal(log.id);
        logsBody.appendChild(tr);
    });
}

const pollingSlider = document.getElementById('polling-slider');
const pollingLabel = document.getElementById('polling-label');

let currentPollIntervalId = null;

// Handle slider changes
pollingSlider.addEventListener('input', (e) => {
    pollingLabel.innerText = `Check every: ${e.target.value}m`;
});

// Update backend when user finishes dragging slider
pollingSlider.addEventListener('change', async (e) => {
    const mins = parseInt(e.target.value);
    const secs = mins * 60;
    try {
        await fetch(`${API_BASE}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ polling_interval_seconds: secs })
        });
        console.log(`Updated backend polling interval to ${mins}m`);
    } catch (err) {
        console.error("Failed to update polling setting:", err);
    }
});

// Fetch Settings
const toggleTrackingBtn = document.getElementById('toggle-tracking-btn');
const trackingPulse = document.getElementById('tracking-pulse');
const trackingBadge = document.getElementById('tracking-badge');
let isTrackingEnabled = true;

function updateTrackingUI(enabled) {
    isTrackingEnabled = enabled;
    if (enabled) {
        toggleTrackingBtn.innerText = "Tracking: ON";
        toggleTrackingBtn.classList.remove('inactive');
        toggleTrackingBtn.classList.add('active');
        trackingPulse.classList.remove('inactive');
        trackingBadge.classList.remove('inactive');
        trackingBadge.innerText = "Live";
    } else {
        toggleTrackingBtn.innerText = "Tracking: OFF";
        toggleTrackingBtn.classList.remove('active');
        toggleTrackingBtn.classList.add('inactive');
        trackingPulse.classList.add('inactive');
        trackingBadge.classList.add('inactive');
        trackingBadge.innerText = "Paused";
    }
}

toggleTrackingBtn.addEventListener('click', async () => {
    const newState = !isTrackingEnabled;
    try {
        await fetch(`${API_BASE}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tracking_enabled: newState })
        });
        updateTrackingUI(newState);
    } catch (err) {
        console.error("Failed to toggle tracking:", err);
    }
});

async function fetchSettings() {
    try {
        const res = await fetch(`${API_BASE}/api/settings`);
        const data = await res.json();
        const mins = Math.max(1, Math.floor(data.polling_interval_seconds / 60));
        pollingSlider.value = mins;
        pollingLabel.innerText = `Check every: ${mins}m`;

        if (data.tracking_enabled !== undefined) {
            updateTrackingUI(data.tracking_enabled);
        }
    } catch (err) {
        console.error("Error fetching settings:", err);
    }
}

// Modal Logic
const modalOverlay = document.getElementById('summary-modal');
const closeModalBtn = document.getElementById('close-modal-btn');
const summaryText = document.getElementById('summary-text');

async function openSummaryModal(logId) {
    modalOverlay.classList.remove('hidden');
    summaryText.innerHTML = '<span class="pulse-ring" style="display:inline-block; margin-right:10px"></span> Generating AI insights...';

    try {
        const res = await fetch(`${API_BASE}/api/summary/${logId}`);
        if (res.ok) {
            const data = await res.json();
            summaryText.innerText = data.summary;
        } else {
            summaryText.innerText = "Wow, 404... I couldn't find any insights for this event!";
        }
    } catch (err) {
        summaryText.innerText = "Error connecting to the AI brain.";
    }
}

closeModalBtn.addEventListener('click', () => {
    modalOverlay.classList.add('hidden');
});
modalOverlay.addEventListener('click', (e) => {
    if (e.target === modalOverlay) {
        modalOverlay.classList.add('hidden');
    }
});

// Hourly Summaries
async function fetchHourlySummaries() {
    try {
        const res = await fetch(`${API_BASE}/api/hourly-summaries?limit=4`);
        const data = await res.json();
        const list = document.getElementById('summaries-list');
        if (!data.length) {
            list.innerHTML = '<p style="color:var(--text-secondary);padding:1rem">No summaries yet — they generate automatically each hour.</p>';
            return;
        }
        list.innerHTML = data.map(s => {
            let timeStr = s.hour_start;
            if (!timeStr.endsWith('Z')) timeStr += 'Z';
            const time = new Date(timeStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const score = s.productivity_score != null ? s.productivity_score.toFixed(1) : '—';
            return `
                <div class="summary-card">
                    <span class="summary-time">${time}</span>
                    <span class="summary-score">${score}/10</span>
                    <p>${s.summary_text}</p>
                </div>`;
        }).join('');
    } catch (err) {
        console.error("Error fetching hourly summaries:", err);
    }
}

// Event Listeners and Poll
refreshBtn.addEventListener('click', () => { fetchData(); fetchHourlySummaries(); });

// Setup
fetchSettings();
fetchData();
fetchHourlySummaries();
currentPollIntervalId = setInterval(() => { fetchData(); fetchHourlySummaries(); }, 5000);
