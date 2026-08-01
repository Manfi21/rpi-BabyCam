function toggleConfig(contentId, iconId) {
    const content = document.getElementById(contentId);
    const icon = document.getElementById(iconId);
    if (content.style.display === 'none' || content.style.display === '') {
        content.style.display = 'block';
        icon.classList.remove('collapsed');
        icon.classList.add('expanded');
    } else {
        content.style.display = 'none';
        icon.classList.remove('expanded');
        icon.classList.add('collapsed');
    }
}
function toggleEdit(configType) {
    const displayDiv = document.getElementById(configType + 'Display');
    const editDiv = document.getElementById(configType + 'Edit');
    const textArea = document.getElementById(configType + 'ConfigRaw');
    if (displayDiv.style.display !== 'none') {
        displayDiv.style.display = 'none';
        editDiv.style.display = 'block';
        const rawJsonElement = document.getElementById(configType + 'RawJson');
        if (rawJsonElement) {
            try {
                const rawJson = rawJsonElement.textContent.trim();
                const parsed = JSON.parse(rawJson);
                textArea.value = JSON.stringify(parsed, null, 4);
            } catch (e) {
                console.error("Error loading JSON into editor:", e);
                textArea.value = '{"error": "loading JSON into editor."}';
                showMessage(`Error config file for ${configType}.`, true);
            }
        } else {
            textArea.value = '{"error": "JSON not found."}';
            showMessage(`Error: JSON for ${configType} not found.`, true);
        }
    } else {
        editDiv.style.display = 'none';
        displayDiv.style.display = 'block';
    }
}
async function saveConfig(configType) {
    const textArea = document.getElementById(configType + 'ConfigRaw');
    const jsonString = textArea.value;
    let configData;
    try {
        configData = JSON.parse(jsonString);
    } catch (e) {
        showMessage('Invalid JSON format', true);
        return;
    }
    // API Endpunkt bestimmen
    let apiEndpoint = '';
    if (configType === 'global') {
        apiEndpoint = '/api/mediamtx/global'; // Proxied to /v3/config/global/set
    } else if (configType === 'pathCam') {
        apiEndpoint = '/api/mediamtx/cam'; // Proxied to /v3/config/paths/set/cam
    } else {
        showMessage('Unkown config type.', true);
        return;
    }
    try {
        showMessage(`Set new config (${configType})...`);
        const response = await fetch(apiEndpoint, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(configData)
        });
        const result = await response.json();
        if (response.ok) {
            showMessage(`Config (${configType}) saved successfully. Website will be reloaded.`);
            toggleEdit(configType);
            setTimeout(() => window.location.reload(), 2000);
        } else {
            let errorDetails = result.error || JSON.stringify(result);
            showMessage(`Error saving config (${configType}): ${errorDetails}`, true);
        }
    } catch (e) {
        console.error("API Fetch Error:", e);
        showMessage('Networkerror while sending new config. Server is reachable?', true);
    }
}

async function loadTuningFiles() {
    const select = document.getElementById('tuningFileSelect');
    if (!select) return;

    try {
        const res = await fetch('/api/mediamtx/tuning-files');
        const data = await res.json();

        (data.files || []).forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        });

        const currentFull = select.dataset.current || '';
        select.value = currentFull.split('/').pop();
    } catch (e) {
        console.error('Error loading tuning files:', e);
    }
}

async function saveTuningFile() {
    const select = document.getElementById('tuningFileSelect');
    const filename = select.value;
    const fullPath = filename ? `/usr/share/libcamera/ipa/rpi/vc4/${filename}` : '';

    showConfirmation(`Set camera tuning file to "${filename || 'None'}"? This writes mediamtx.yml directly and restarts the camera server.`, async (confirmed) => {
        if (!confirmed) return;

        try {
            const response = await fetch('/api/mediamtx/tuning-file', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({tuning_file: fullPath})
            });

            if (response.ok) {
                setTimeout(() => sys_stream('restart_cameraserver'), 500);
            } else {
                const result = await response.json();
                showMessage('Error: ' + result.message, true);
            }
        } catch (e) {
            showMessage('Network error while saving.', true);
        }
    });
}

document.addEventListener('DOMContentLoaded', loadTuningFiles);

// -----------------------
// Camera Crop (ROI) selector
// -----------------------
const cropState = {
    width: 1920,
    height: 1080,
    currentRoi: [0, 0, 1, 1], // x, y, w, h of the currently VISIBLE frame, relative to the full sensor
    dragging: false,
    startX: 0,
    startY: 0,
    stageW: 0,
    stageH: 0,
    rect: null // {x, y, w, h} normalized to the currently visible frame (0-1)
};

function parseRoi(str) {
    if (!str) return [0, 0, 1, 1];
    const parts = str.split(',').map(Number);
    if (parts.length !== 4 || parts.some(isNaN)) return [0, 0, 1, 1];
    return parts;
}

function openCropSelector() {
    const btn = document.getElementById('openCropBtn');
    cropState.width = parseInt(btn.dataset.width, 10) || 1920;
    cropState.height = parseInt(btn.dataset.height, 10) || 1080;
    cropState.currentRoi = parseRoi(btn.dataset.currentRoi);
    cropState.rect = null;

    document.getElementById('cropStage').style.aspectRatio = `${cropState.width} / ${cropState.height}`;

    const sel = document.getElementById('cropSelection');
    sel.style.display = 'none';

    const host = window.location.hostname;
    const postfix = btn.dataset.postfix || '/cam';
    document.getElementById('cropFrame').src = `http://${host}:8889${postfix}?muted=1`;

    document.getElementById('cropModal').style.display = 'flex';
}

function closeCropSelector() {
    document.getElementById('cropModal').style.display = 'none';
    document.getElementById('cropFrame').src = '';
}

function cropPointerPos(e, overlay) {
    const rect = overlay.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return {
        x: Math.min(Math.max(clientX - rect.left, 0), rect.width),
        y: Math.min(Math.max(clientY - rect.top, 0), rect.height),
        w: rect.width,
        h: rect.height
    };
}

function setupCropOverlayEvents() {
    const overlay = document.getElementById('cropOverlay');
    const sel = document.getElementById('cropSelection');
    if (!overlay || !sel) return;

    function start(e) {
        const p = cropPointerPos(e, overlay);
        cropState.dragging = true;
        cropState.startX = p.x;
        cropState.startY = p.y;
        cropState.stageW = p.w;
        cropState.stageH = p.h;
        sel.style.left = p.x + 'px';
        sel.style.top = p.y + 'px';
        sel.style.width = '0px';
        sel.style.height = '0px';
        sel.style.display = 'block';
        e.preventDefault();
    }

    function move(e) {
        if (!cropState.dragging) return;
        const p = cropPointerPos(e, overlay);
        const left = Math.min(p.x, cropState.startX);
        const top = Math.min(p.y, cropState.startY);
        const width = Math.abs(p.x - cropState.startX);
        const height = Math.abs(p.y - cropState.startY);
        sel.style.left = left + 'px';
        sel.style.top = top + 'px';
        sel.style.width = width + 'px';
        sel.style.height = height + 'px';
        e.preventDefault();
    }

    function end() {
        if (!cropState.dragging) return;
        cropState.dragging = false;
        const w = parseFloat(sel.style.width);
        const h = parseFloat(sel.style.height);
        if (w < 10 || h < 10) {
            sel.style.display = 'none';
            cropState.rect = null;
            return;
        }
        cropState.rect = {
            x: parseFloat(sel.style.left) / cropState.stageW,
            y: parseFloat(sel.style.top) / cropState.stageH,
            w: w / cropState.stageW,
            h: h / cropState.stageH
        };
    }

    overlay.addEventListener('mousedown', start);
    overlay.addEventListener('mousemove', move);
    overlay.addEventListener('mouseup', end);
    overlay.addEventListener('touchstart', start, {passive: false});
    overlay.addEventListener('touchmove', move, {passive: false});
    overlay.addEventListener('touchend', end);
}

document.addEventListener('DOMContentLoaded', setupCropOverlayEvents);

function composeRoi(base, sel) {
    const [ox, oy, ow, oh] = base;
    const nx = ox + sel.x * ow;
    const ny = oy + sel.y * oh;
    const nw = sel.w * ow;
    const nh = sel.h * oh;
    return [nx, ny, nw, nh].map(v => Math.max(0, Math.min(1, v)));
}

function applyCropSelection() {
    if (!cropState.rect) {
        showMessage('Please drag a selection on the image first.', true);
        return;
    }
    const [x, y, w, h] = composeRoi(cropState.currentRoi, cropState.rect).map(v => v.toFixed(4));
    const roiString = `${x},${y},${w},${h}`;
    closeCropSelector();
    submitRoi(roiString, `Apply crop ${roiString}? This writes mediamtx.yml and restarts the camera server.`);
}

function resetCropSelection() {
    closeCropSelector();
    submitRoi('', 'Reset crop to full frame? This writes mediamtx.yml and restarts the camera server.');
}

function submitRoi(roiString, confirmMsg) {
    showConfirmation(confirmMsg, async (confirmed) => {
        if (!confirmed) return;

        try {
            const response = await fetch('/api/mediamtx/roi', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({roi: roiString})
            });

            if (response.ok) {
                setTimeout(() => sys_stream('restart_cameraserver'), 500);
            } else {
                const result = await response.json();
                showMessage('Error: ' + result.message, true);
            }
        } catch (e) {
            showMessage('Network error while saving.', true);
        }
    });
}

const modal = document.getElementById('customModal');
const modalMessage = document.getElementById('modalMessage');
const modalConfirmBtn = document.getElementById('modalConfirmBtn');
const modalCancelBtn = document.getElementById('modalCancelBtn');
const modalOkBtn = document.getElementById('modalOkBtn');

function showMessage(message, isError = false) {
    modalMessage.innerHTML = message;
    modalMessage.style.color = isError ? '#dc3545' : '#eee';
    modalConfirmBtn.style.display = 'none';
    modalCancelBtn.style.display = 'none';
    modalOkBtn.style.display = 'block';
    modalOkBtn.onclick = () => modal.style.display = 'none';
    modal.style.display = 'flex';
}

function showConfirmation(message, callback) {
    modalMessage.innerHTML = message;
    modalMessage.style.color = '#eee';
    modalOkBtn.style.display = 'none';
    modalConfirmBtn.style.display = 'block';
    modalCancelBtn.style.display = 'block';

    modalConfirmBtn.onclick = () => {
        modal.style.display = 'none';
        callback(true);
    };
    modalCancelBtn.onclick = () => {
        modal.style.display = 'none';
        callback(false);
    };
    modal.style.display = 'flex';
}
let streamSource = null;

function openStream() {
    document.getElementById('streamOutput').innerText = "";
    document.getElementById('streamModal').style.display = 'flex';
}

function closeStream() {
    if (streamSource) {
        streamSource.close();
        streamSource = null;
    }
    document.getElementById('streamModal').style.display = 'none';
}

function sys(action) {
    showConfirmation(`System ${action}?`, confirmed => {
        if (!confirmed) return;

        fetch('/api/system', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: action})
        })
        .then(res => res.json())
        .then(data => showMessage(data.status || "Done"));
    });
}
function sys_stream(action) {
    document.getElementById("streamOutput").innerText = "";
    document.getElementById("streamModal").style.display = "flex";

    // vorherigen Stream schließen
    if (streamSource) {
        streamSource.close();
        streamSource = null;
    }

    // Stream starten (GET mit Query)
    streamSource = new EventSource("/api/system/stream?action=" + action);

    // Live Output
    streamSource.onmessage = (event) => {
        const out = document.getElementById("streamOutput");
        out.textContent += event.data + "\n";
        out.scrollTop = out.scrollHeight;

        if (event.data.includes("--- DONE ---")) {
            streamSource.close();
        }
    };

    streamSource.onerror = () => {
        const out = document.getElementById("streamOutput");
        out.textContent += "\n[Connection closed]\n";
        streamSource.close();
    };
}

window.onload = function() {
    localStorage.removeItem('stream_postfix');
}
function showManualMode() {
    document.getElementById('scanMode').style.display = 'none';
    document.getElementById('manualMode').style.display = 'block';
    document.getElementById('wifiStatusMessage').style.display = 'none';
}
function showScanMode() {
    document.getElementById('scanMode').style.display = 'block';
    document.getElementById('manualMode').style.display = 'none';
}
function scanWifi() {
    const list = document.getElementById('wifiList');
    const btn = document.getElementById('scanBtn');
    const statusMsg = document.getElementById('wifiStatusMessage');
    showScanMode();
    list.style.display = 'block';
    list.innerHTML = '<div style="padding:10px;">Scanning for networks...</div>';
    statusMsg.style.display = 'none';
    btn.disabled = true;
    fetch('/api/scan')
    .then(res => {
        if (!res.ok) {
            throw new Error('Scan API failed');
        }
        return res.json();
    })
    .then(data => {
        list.innerHTML = '';
        btn.disabled = false;
        if(data.networks.length === 0) {
            list.innerHTML = '<div style="padding:10px;">No network found.</div>';
            return;
        }
        data.networks.forEach(ssid => {
            const div = document.createElement('div');
            div.className = 'wifi-item';
            div.innerText = ssid;
            div.onclick = () => selectWifi(ssid);
            list.appendChild(div);
        });
    })
    .catch(err => {
        console.error("Scan Error:", err);
        statusMsg.className = 'error-message';
        statusMsg.innerHTML = 'Scan failed. Camera in Access Point Mode?';
        statusMsg.style.display = 'block';
        list.style.display = 'none';
        btn.disabled = false;
        showManualMode();
    });
}
function selectWifi(ssid) {
    document.getElementById('ssidInput').value = ssid;
    document.getElementById('connectForm').style.display = 'block';
    document.getElementById('pwInput').focus();
}
function connectWifi() {
    const ssid = document.getElementById('ssidInput').value;
    const pw = document.getElementById('pwInput').value;
    sendWifiConfig(ssid, pw, 'Available Networks');
}
function configureManualWifi() {
    const ssid = document.getElementById('manualSsidInput').value.trim();
    const pw = document.getElementById('manualPwInput').value.trim();
    if (!ssid || !pw) {
        showMessage('SSID and password must not be empty!', true);
        return;
    }
    sendWifiConfig(ssid, pw, 'Manual input');
}
function sendWifiConfig(ssid, pw, mode) {
    showConfirmation(`WIFI "${ssid}" (${mode}) save and restart?`, (confirmed) => {
        if (!confirmed) return;

        fetch('/api/wifi', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssid: ssid, password: pw})
        })
        .then(res => {
            if (res.ok) {
                showMessage(`New data saved for "${ssid}". System restart`, false);
            } else {
                return res.json().then(data => { throw new Error(data.message || 'Unknown error'); });
            }
        })
        .catch(err => {
            console.error("WiFi Config Error:", err);
            showMessage(`Error while saving config: ${err.message || 'Networkerror.'}`, true);
        });
    });
}

async function saveHostname() {
    const input = document.getElementById('hostnameInput');
    const hostname = input.value.trim();

    if (!hostname) {
        showMessage('Hostname must not be empty', true);
        return;
    }

    showConfirmation(`Set hostname to "${hostname}"?`, async (confirmed) => {
        if (!confirmed) return;

        try {
            const res = await fetch('/api/hostname', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({hostname: hostname})
            });
            const data = await res.json();
            if (res.ok) {
                showMessage(data.message || 'Hostname updated');
            } else {
                showMessage(data.message || 'Failed to update hostname', true);
            }
        } catch (e) {
            showMessage('Network error: ' + e.message, true);
        }
    });
}
async function saveAuthUser() {
    const user = document.getElementById('authUserInput').value.trim();
    const pass = document.getElementById('authPassInput').value.trim();

    if (!user) {
        showMessage('Username is required', true);
        return;
    }

    showConfirmation(`Save credentials for "${user}"?`, async (confirmed) => {
        if (!confirmed) return;

        try {
            const res = await fetch('/api/auth_user', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({user: user, password: pass})
            });
            const data = await res.json();
            if (res.ok) {
                showMessage(data.message || 'Credentials saved');
            } else {
                showMessage(data.error || 'Failed to save credentials', true);
            }
        } catch (e) {
            showMessage('Network error: ' + e.message, true);
        }
    });
}

async function disableAuthUser() {
    showConfirmation('Disable password and allow any user?', async (confirmed) => {
        if (!confirmed) return;

        try {
            const res = await fetch('/api/auth_user', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({user: 'any', password: ''})
            });
            const data = await res.json();
            if (res.ok) {
                document.getElementById('authUserInput').value = '';
                document.getElementById('authPassInput').value = '';
                showMessage(data.message || 'Password disabled, any user allowed');
            } else {
                showMessage(data.error || 'Failed to disable password', true);
            }
        } catch (e) {
            showMessage('Network error: ' + e.message, true);
        }
    });
}

function savePostfixToLocal() {
    let postfix = document.getElementById('streamPostfixInput').value.trim();
    if (!postfix.startsWith("/")) postfix = "/" + postfix;
    localStorage.setItem("stream_postfix", postfix);
}

async function loadVersionInfo() {
    try {
        const response = await fetch('/api/version');
        const data = await response.json();

        if (data.version) {
            document.getElementById('version_os').innerText = data.version;
            document.getElementById('version_os_full').innerText = data.full_build;
            document.getElementById('build_date').innerText = data.build_date;
            document.getElementById('webserver_version').innerText = data.webserver_version;
            document.getElementById('mediamtx_version').innerText = data.mediamtx_version;
        }
    } catch (error) {
        console.error('Error fetching version info:', error);
        document.getElementById('version_os').innerText = "Error";
    }
}

document.addEventListener('DOMContentLoaded', loadVersionInfo);

async function openEditor() {
    try {
        const response = await fetch('/api/get_config_file');
        if (!response.ok) throw new Error('Could not load config file.');

        const content = await response.text();
        const editor = document.getElementById('fullConfigEditor');

        editor.value = content;
        document.getElementById('editorModal').style.display = 'flex';
        editor.scrollTop = 0;

        editor.onkeydown = function(e) {
            if (e.key === 'Tab') {
                e.preventDefault();
                const start = this.selectionStart;
                const end = this.selectionEnd;
                this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
                this.selectionStart = this.selectionEnd = start + 2;
            }
        };
    } catch (e) {
        showMessage('Error: ' + e.message, true);
    }
}

function closeEditor() {
    document.getElementById('editorModal').style.display = 'none';
}

async function saveFullConfig() {
    const content = document.getElementById('fullConfigEditor').value;
    closeEditor();

    showConfirmation("Overwrite mediamtx.yml?", async (confirmed) => {
        if (!confirmed) return;

        try {
            const response = await fetch('/api/save_config_file', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({content: content})
            });

            if (response.ok) {
                setTimeout(() => sys_stream('restart_cameraserver'), 500);
            } else {
                const result = await response.json();
                showMessage('Error: ' + result.message, true);
            }
        } catch (e) {
            showMessage('Network error while saving.', true);
        }
    });
}

// -----------------------
// System Monitor
// -----------------------
let statsInterval = null;

function gaugeColor(percent) {
    if (percent >= 90) return 'var(--bad)';
    if (percent >= 70) return 'var(--warn)';
    return 'var(--good)';
}

function setGauge(prefix, percent, color) {
    const gauge = document.getElementById(prefix + 'Gauge');
    const valueEl = document.getElementById(prefix + 'Value');
    if (!gauge || !valueEl) return;
    const clamped = Math.max(0, Math.min(100, percent));
    gauge.style.setProperty('--pct', clamped);
    gauge.style.setProperty('--color', color);
    valueEl.textContent = Math.round(percent);
}

function formatUptime(seconds) {
    seconds = Math.floor(seconds);
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const parts = [];
    if (d) parts.push(d + 'd');
    if (d || h) parts.push(h + 'h');
    parts.push(m + 'm');
    return parts.join(' ');
}

async function refreshSystemStats() {
    try {
        const res = await fetch('/api/system/stats');
        if (!res.ok) throw new Error('stats request failed');
        const data = await res.json();

        setGauge('cpu', data.cpu_percent, gaugeColor(data.cpu_percent));
        setGauge('mem', data.memory.percent, gaugeColor(data.memory.percent));
        setGauge('disk', data.disk.percent, gaugeColor(data.disk.percent));

        const tempValueEl = document.getElementById('tempValue');
        if (data.temperature_c !== null && data.temperature_c !== undefined) {
            const tempPct = Math.min(100, (data.temperature_c / 90) * 100);
            const tempColor = data.temperature_c >= 75 ? 'var(--bad)' : (data.temperature_c >= 60 ? 'var(--warn)' : 'var(--good)');
            setGauge('temp', tempPct, tempColor);
            tempValueEl.textContent = data.temperature_c.toFixed(1);
        } else {
            tempValueEl.textContent = '–';
        }

        document.getElementById('cpuCoreCount').textContent = data.cpu_count + (data.cpu_count === 1 ? ' core' : ' cores');
        document.getElementById('memDetail').textContent = `${data.memory.used_mb} / ${data.memory.total_mb} MB`;
        document.getElementById('diskDetail').textContent = `${data.disk.used_gb} / ${data.disk.total_gb} GB`;
        document.getElementById('loadAverage').textContent = `${data.load_average['1min']} / ${data.load_average['5min']} / ${data.load_average['15min']}`;
        document.getElementById('uptimeValue').textContent = formatUptime(data.uptime_seconds);
    } catch (e) {
        console.error('Error fetching system stats:', e);
    }
}

function startSystemStats() {
    refreshSystemStats();
    clearInterval(statsInterval);
    statsInterval = setInterval(refreshSystemStats, 2000);
}

document.addEventListener('DOMContentLoaded', startSystemStats);
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        clearInterval(statsInterval);
    } else {
        startSystemStats();
    }
});

// -----------------------
// System Logs
// -----------------------
let logSource = null;
let logsPanelOpen = false;
let currentLogSource = 'webadmin';

function updateLogStatus(state, label) {
    const dot = document.getElementById('logStatusDot');
    const labelEl = document.getElementById('logStatusLabel');
    if (!dot || !labelEl) return;
    dot.className = 'status-dot status-' + state;
    labelEl.textContent = label;
}

function appendLogLine(line) {
    const out = document.getElementById('logOutput');
    const atBottom = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;

    const div = document.createElement('div');
    div.className = 'log-line';
    div.textContent = line;
    out.appendChild(div);

    while (out.childElementCount > 500) {
        out.removeChild(out.firstChild);
    }

    const autoscroll = document.getElementById('logAutoscroll');
    if (autoscroll && autoscroll.checked && atBottom) {
        out.scrollTop = out.scrollHeight;
    }
}

function connectLogs(source) {
    currentLogSource = source;
    if (logSource) {
        logSource.close();
        logSource = null;
    }
    document.getElementById('logOutput').textContent = '';
    updateLogStatus('connecting', 'Connecting…');

    logSource = new EventSource('/api/logs/stream?source=' + encodeURIComponent(source));
    logSource.onopen = () => updateLogStatus('live', 'Live');
    logSource.onmessage = (event) => appendLogLine(event.data);
    logSource.onerror = () => updateLogStatus('error', 'Connection error');

    document.getElementById('logToggleBtn').textContent = 'Pause';
}

function selectLogSource(source, btn) {
    document.querySelectorAll('.log-source-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    connectLogs(source);
}

function toggleLogStream() {
    const btn = document.getElementById('logToggleBtn');
    if (logSource) {
        logSource.close();
        logSource = null;
        updateLogStatus('paused', 'Paused');
        btn.textContent = 'Resume';
    } else {
        connectLogs(currentLogSource);
    }
}

function clearLogView() {
    document.getElementById('logOutput').textContent = '';
}

function toggleLogsPanel() {
    const content = document.getElementById('logsWrapper');
    const icon = document.getElementById('logsToggle');
    logsPanelOpen = !logsPanelOpen;

    if (logsPanelOpen) {
        content.style.display = 'block';
        icon.classList.add('expanded');
        connectLogs(currentLogSource);
    } else {
        content.style.display = 'none';
        icon.classList.remove('expanded');
        if (logSource) {
            logSource.close();
            logSource = null;
        }
        updateLogStatus('disconnected', 'Disconnected');
    }
}

window.addEventListener('beforeunload', () => {
    if (logSource) logSource.close();
});
