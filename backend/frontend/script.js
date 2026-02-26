const API_BASE = '';

// DOM Elements
const clockEl = document.getElementById('clock');
const macStatus = document.getElementById('mac-status');
const macDetail = document.getElementById('mac-detail');
const iosStatus = document.getElementById('ios-status');
const iosDetail = document.getElementById('ios-detail');
const focusStatus = document.getElementById('focus-status');
const focusDetail = document.getElementById('focus-detail');
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
        if(latestMac.is_idle) macDetail.style.color = "var(--warning)";
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

    // 4. Update Logs Table
    logsBody.innerHTML = '';
    logs.forEach((log, index) => {
        const tr = document.createElement('tr');
        tr.className = 'fade-in';
        tr.style.animationDelay = `${index * 0.05}s`;
        
        const time = new Date(log.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        const isMac = log.device === 'mac';
        
        let activityText = "";
        let contextText = "";
        
        if (isMac) {
            activityText = log.app_name;
            // Safari/Chrome now send "Tab Name - URL"
            let titleText = log.window_title;
            if(titleText) {
                // Formatting
                if(titleText.length > 55) titleText = titleText.substring(0, 55) + "...";
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
        logsBody.appendChild(tr);
    });
}

// Event Listeners and Poll
refreshBtn.addEventListener('click', fetchData);

// Initial fetch and poll every 5 seconds
fetchData();
setInterval(fetchData, 5000);
