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
// Camera Zoom / Crop (pan & zoom ROI selector)
// -----------------------
const CROP_MAX_ZOOM = 8;
const CROP_ZOOM_STEP = 1.1;

const cropState = {
    width: 1920,
    height: 1080,
    roi: [0, 0, 1, 1],  // currently applied ROI (normalized to the full frame)
    scale: 1,           // 1 = current stream view fills the stage
    tx: 0,              // iframe translate X (px)
    ty: 0,              // iframe translate Y (px)
    stageW: 0,
    stageH: 0,
    panning: false,
    panStartX: 0,
    panStartY: 0,
    panStartTx: 0,
    panStartTy: 0
};

function parseRoi(str) {
    if (!str) return [0, 0, 1, 1];
    const parts = str.split(',').map(Number);
    if (parts.length !== 4 || parts.some(isNaN)) return [0, 0, 1, 1];
    return parts;
}

function applyCropTransform() {
    const frame = document.getElementById('cropFrame');
    if (!frame) return;
    frame.style.transform = `translate(${cropState.tx}px, ${cropState.ty}px) scale(${cropState.scale})`;
}

// Visible box inside the current stream frame (normalized), for the given scale + translate
function visibleView() {
    const s = cropState.scale;
    const W = cropState.stageW, H = cropState.stageH;
    return {
        x: -cropState.tx / (s * W),
        y: -cropState.ty / (s * H),
        w: 1 / s,
        h: 1 / s
    };
}

function clampPan() {
    const v = visibleView();
    const maxX = 1 - v.w;
    const maxY = 1 - v.h;
    const x = Math.max(0, Math.min(v.x, maxX));
    const y = Math.max(0, Math.min(v.y, maxY));
    if (x !== v.x) cropState.tx = -x * cropState.scale * cropState.stageW;
    if (y !== v.y) cropState.ty = -y * cropState.scale * cropState.stageH;
}

function updateCropReadout() {
    const zoomEl = document.getElementById('cropZoomLabel');
    const sizeEl = document.getElementById('cropSizeLabel');
    if (!zoomEl) return;
    const v = visibleView();
    zoomEl.textContent = cropState.scale.toFixed(1) + '×';
    if (sizeEl) {
        sizeEl.textContent = `${Math.round(v.w * cropState.width)} × ${Math.round(v.h * cropState.height)} px`;
    }
}

function updateCrop() {
    clampPan();
    applyCropTransform();
    updateCropReadout();
}

// Zoom around a stage point (cx, cy). factor > 1 zooms in, factor < 1 zooms out.
function cropZoomAt(cx, cy, factor) {
    const oldScale = cropState.scale;
    const newScale = Math.max(1, Math.min(CROP_MAX_ZOOM, oldScale * factor));
    if (newScale === oldScale) return;

    // content point currently under the cursor
    const px = (cx - cropState.tx) / (oldScale * cropState.stageW);
    const py = (cy - cropState.ty) / (oldScale * cropState.stageH);

    cropState.scale = newScale;
    cropState.tx = cx - px * newScale * cropState.stageW;
    cropState.ty = cy - py * newScale * cropState.stageH;
    updateCrop();
}

function cropZoom(zoomIn) {
    const stage = document.getElementById('cropStage');
    const r = stage.getBoundingClientRect();
    cropZoomAt(r.width / 2, r.height / 2, zoomIn ? CROP_ZOOM_STEP : 1 / CROP_ZOOM_STEP);
}

function resetCropView() {
    cropState.scale = 1;
    cropState.tx = 0;
    cropState.ty = 0;
    updateCrop();
}

function openCropSelector() {
    const btn = document.getElementById('openCropBtn');
    const stage = document.getElementById('cropStage');
    cropState.width = parseInt(btn.dataset.width, 10) || 1920;
    cropState.height = parseInt(btn.dataset.height, 10) || 1080;
    cropState.roi = parseRoi(btn.dataset.currentRoi);
    cropState.scale = 1;
    cropState.tx = 0;
    cropState.ty = 0;

    stage.style.aspectRatio = `${cropState.width} / ${cropState.height}`;
    document.getElementById('cropModal').style.display = 'flex';

    const rect = stage.getBoundingClientRect();
    cropState.stageW = rect.width;
    cropState.stageH = rect.height;

    applyCropTransform();
    updateCropReadout();

    const host = window.location.hostname;
    const protocol = window.location.protocol;
    const postfix = btn.dataset.postfix || '/cam';
    document.getElementById('cropFrame').src = `${protocol}//${host}:8889${postfix}?muted=1`;
}

function closeCropSelector() {
    document.getElementById('cropModal').style.display = 'none';
    const frame = document.getElementById('cropFrame');
    frame.src = '';
    frame.style.transform = '';
}

function cropStagePos(e) {
    const rect = document.getElementById('cropStage').getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return {x: clientX - rect.left, y: clientY - rect.top};
}

function setupCropEvents() {
    const stage = document.getElementById('cropStage');
    if (!stage) return;

    // Wheel zoom (non-passive so we can preventDefault the page scroll)
    stage.addEventListener('wheel', (e) => {
        e.preventDefault();
        const pos = cropStagePos(e);
        cropZoomAt(pos.x, pos.y, e.deltaY < 0 ? CROP_ZOOM_STEP : 1 / CROP_ZOOM_STEP);
    }, {passive: false});

    stage.addEventListener('dblclick', (e) => {
        const pos = cropStagePos(e);
        cropZoomAt(pos.x, pos.y, CROP_ZOOM_STEP);
    });

    function start(e) {
        if (cropState.scale <= 1) return;
        cropState.panning = true;
        const pos = cropStagePos(e);
        cropState.panStartX = pos.x;
        cropState.panStartY = pos.y;
        cropState.panStartTx = cropState.tx;
        cropState.panStartTy = cropState.ty;
        stage.style.cursor = 'grabbing';
        e.preventDefault();
    }
    function move(e) {
        if (!cropState.panning) return;
        const pos = cropStagePos(e);
        cropState.tx = cropState.panStartTx + (pos.x - cropState.panStartX);
        cropState.ty = cropState.panStartTy + (pos.y - cropState.panStartY);
        updateCrop();
        e.preventDefault();
    }
    function end() {
        if (!cropState.panning) return;
        cropState.panning = false;
        stage.style.cursor = '';
    }

    stage.addEventListener('mousedown', start);
    stage.addEventListener('mousemove', move);
    stage.addEventListener('mouseup', end);
    stage.addEventListener('mouseleave', end);
    stage.addEventListener('touchstart', start, {passive: false});
    stage.addEventListener('touchmove', move, {passive: false});
    stage.addEventListener('touchend', end);
}

document.addEventListener('DOMContentLoaded', setupCropEvents);

function applyCropSelection() {
    if (cropState.scale <= 1) {
        showMessage('Zoom in first, then press Apply & Save.', true);
        return;
    }
    const v = visibleView();
    const [rx, ry, rw, rh] = cropState.roi;
    const x = rx + v.x * rw;
    const y = ry + v.y * rh;
    const w = v.w * rw;
    const h = v.h * rh;
    const roiString = [x, y, w, h].map(v => v.toFixed(4)).join(',');

    closeCropSelector();
    submitRoi(roiString, `Apply zoom ${roiString}? The crop is applied live, no restart needed.`);
}

function resetCropSelection() {
    closeCropSelector();
    submitRoi('', 'Reset crop to full frame?');
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
            const result = await response.json();
            if (response.ok) {
                showMessage(result.message || 'Crop saved.');
            } else {
                showMessage('Error: ' + (result.message || 'Unknown error'), true);
            }
        } catch (e) {
            showMessage('Network error while saving.', true);
        }
    });
}

// -----------------------
// Audio settings
// -----------------------
async function loadAudioControls() {
    const select = document.getElementById('audioControlSelect');
    if (!select) return;

    try {
        const res = await fetch('/api/audio/controls');
        const data = await res.json();

        select.innerHTML = '';
        (data.controls || []).forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        });

        if (select.options.length > 0) {
            await loadAudioStatus();
        }
    } catch (e) {
        console.error('Error loading audio controls:', e);
    }
}

async function loadAudioStatus() {
    const select = document.getElementById('audioControlSelect');
    const control = select.value;
    if (!control) return;

    try {
        const res = await fetch('/api/audio/status?control=' + encodeURIComponent(control));
        const data = await res.json();
        const percent = data.percent ?? 0;
        const hasVolume = !!data.has_volume;

        document.getElementById('audioVolumeSlider').value = percent;
        document.getElementById('audioVolumeValue').textContent = percent;
        document.getElementById('audioMuteCheckbox').checked = !!data.muted;

        document.getElementById('audioVolumeWrapper').style.display = hasVolume ? '' : 'none';
        document.getElementById('audioApplyVolumeBtn').style.display = hasVolume ? '' : 'none';
    } catch (e) {
        console.error('Error loading audio status:', e);
    }
}

function onAudioVolumeInput() {
    const value = document.getElementById('audioVolumeSlider').value;
    document.getElementById('audioVolumeValue').textContent = value;
}

async function applyAudioVolume() {
    const control = document.getElementById('audioControlSelect').value;
    const percent = parseInt(document.getElementById('audioVolumeSlider').value, 10);

    if (!control) {
        showMessage('No audio control available.', true);
        return;
    }

    try {
        const res = await fetch('/api/audio/volume', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({control: control, percent: percent})
        });
        const data = await res.json();
        if (res.ok) {
            // showMessage(data.message || 'Volume updated');
        } else {
            showMessage(data.message || 'Failed to update volume', true);
        }
    } catch (e) {
        showMessage('Network error: ' + e.message, true);
    }
}

async function applyAudioMute() {
    const control = document.getElementById('audioControlSelect').value;
    const muted = document.getElementById('audioMuteCheckbox').checked;
    if (!control) return;

    try {
        const res = await fetch('/api/audio/mute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({control: control, muted: muted})
        });
        const data = await res.json();
        if (!res.ok) {
            showMessage(data.message || 'Failed to update mute state', true);
        }
    } catch (e) {
        showMessage('Network error: ' + e.message, true);
    }
}

document.addEventListener('DOMContentLoaded', loadAudioControls);

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

// -----------------------
// BabyCam View native app (download field)
// -----------------------
function isNativeApp() {
    return /Electron/i.test(navigator.userAgent);
}

function bcvPlatform() {
    const ua = navigator.userAgent;
    if (/Android/i.test(ua)) return 'android';
    if (/iPhone|iPad|iPod|Mac/i.test(ua)) return 'apple';
    if (/Windows/i.test(ua)) return 'windows';
    return 'linux';
}

function detectClient() {
    if (isNativeApp()) return 'BabyCam View app';
    return 'Browser';
}

function getInstalledAppVersion() {
    const m = navigator.userAgent.match(/(?:babycam|babicam)[^\s/]*\/(\d+\.\d+(?:\.\d+)?)/i);
    return m ? m[1] : null;
}

function semverGt(a, b) {
    const pa = String(a).split('.').map(n => parseInt(n, 10) || 0);
    const pb = String(b).split('.').map(n => parseInt(n, 10) || 0);
    for (let i = 0; i < 3; i++) {
        if ((pa[i] || 0) > (pb[i] || 0)) return true;
        if ((pa[i] || 0) < (pb[i] || 0)) return false;
    }
    return false;
}

async function updateNativeAppButton() {
    const btn = document.getElementById('getNativeAppBtn');
    if (!btn) return;
    try {
        const res = await fetch('/api/babycamview');
        const data = await res.json();
        if (data.status !== 'ok') return;

        const installed = getInstalledAppVersion();
        if (isNativeApp()) {
            if (installed && semverGt(data.version, installed)) {
                btn.textContent = 'Update App (' + data.tag + ')';
                btn.classList.add('btn-update-avail');
            } else {
                btn.textContent = 'App up to date (' + data.tag + ')';
            }
        } else {
            btn.textContent = 'Get Native App (' + data.tag + ')';
        }
    } catch (e) { /* keep default button text */ }
}

async function getNativeApp() {
    try {
        const res = await fetch('/api/babycamview');
        const data = await res.json();
        if (data.status !== 'ok') {
            showMessage('Could not fetch app info: ' + (data.error || 'unknown'), true);
            return;
        }
        const platform = bcvPlatform();
        const url = (data.assets && data.assets[platform]) || data.releases_url;

        if (isNativeApp()) {
            showMessage(
                'BabyCam View ' + data.tag + ' — download it from the <a href="' + data.releases_url +
                '" rel="noopener" style="color: var(--accent);">GitHub releases page</a>.',
                false
            );
            return;
        }

        const a = document.createElement('a');
        a.href = url;
        a.rel = 'noopener';
        a.download = url.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        showMessage('Downloading BabyCam View ' + data.tag + ' for ' + platform + '.');
    } catch (e) {
        showMessage('Network error: ' + e.message, true);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const clientEl = document.getElementById('clientType');
    if (clientEl) clientEl.textContent = detectClient();
    updateNativeAppButton();
});

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
