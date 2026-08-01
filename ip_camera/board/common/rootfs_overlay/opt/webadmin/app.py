import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from functools import wraps
import subprocess
import os
import requests
import json
import time
import hashlib
import base64
import shutil
import socket
import re
import shlex
from update_os_files import compare_and_print_config_changes

app = Flask(__name__)

CONFIG_FILE_PATH = 'stream_postfix.txt'
AUDIO_CONFIG_PATH = 'audio_config.json'
MEDIAMTX_API_HOST= "http://127.0.0.1:9997"
RPI_PREFIX = "rpi"
USER_FILE = '/root/auth_users.txt'
MEDIAMTX_CONFIG_PATH = '/root/mediamtx.yml'
TUNING_FILES_DIR = '/usr/share/libcamera/ipa/rpi/vc4'
THERMAL_ZONE_PATH = '/sys/class/thermal/thermal_zone0/temp'
HOSTNAME_FILE = '/etc/hostname'
HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$')
LOG_SOURCES = {
    'webadmin': '/var/log/webadmin.log',
    'mediamtx': '/var/log/mediamtx.log',
}

_last_cpu_sample = {'total': None, 'idle': None}

# -----------------------
# Helper functions
# -----------------------
def run_command(command, timeout=5):
    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=timeout)
        return result.decode('utf-8', errors='ignore').strip()
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8', errors='ignore').strip()
    except FileNotFoundError:
        return "CMD not found"
    except subprocess.TimeoutExpired:
        return "CMD timeout"
    except Exception as e:
        return str(e)

def hash_credential(cred: str) -> str:
    h = hashlib.sha256(cred.encode("utf-8")).digest()
    return base64.b64encode(h).decode("utf-8")

def get_basic_auth_credentials():
    if not os.path.exists(USER_FILE):
        return None, None
    try:
        line = open(USER_FILE).read().strip()
        if not line or line.startswith("any:"):
            return None, None
        if ":" in line:
            user, pwd = line.split(":", 1)
            return user.strip(), pwd.strip()
        return None, None
    except Exception:
        return None, None

def basic_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        hashed_user, hashed_pass = get_basic_auth_credentials()
        if not hashed_user or not hashed_pass:
            # No auth needed
            return f(*args, **kwargs)

        auth = request.authorization
        if not auth:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'}
            )

        # Hashing of credentials
        input_user_hash = hash_credential(auth.username)
        input_pass_hash = hash_credential(auth.password)

        if input_user_hash != hashed_user or input_pass_hash != hashed_pass:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'}
            )

        return f(*args, **kwargs)
    return decorated

def get_current_ssid():
    try:
        # Get the current status from wpa_supplicant
        raw = run_command("wpa_cli -i wlan0 status")

        if raw:
            # Look for the line starting with 'ssid='
            for line in raw.splitlines():
                if line.startswith("ssid="):
                    return line.split("=", 1)[1].strip()

    except Exception as e:
        print(f"[ERROR] Could not get current SSID: {str(e)}")

    return "Not connected"

def get_ip_address():
    try:
        ip = run_command("ip -4 addr show wlan0 | grep inet | awk '{print $2}' | cut -d/ -f1 | head -n 1")
        if ip:
            return ip
        else:
            ip = run_command("ip -4 addr show eth0 | grep inet | awk '{print $2}' | cut -d/ -f1 | head -n 1")
        if ip:
            return ip
        return "No IP"
    except Exception:
        return "No IP"

def get_ip_tailscale_address():
    try:
        ip = run_command("ip -4 addr show tailscale0 | grep inet | awk '{print $2}' | cut -d/ -f1 | head -n 1")
        if ip:
            return ip
        return "Not connected"
    except Exception:
        return "Not connected"

def get_hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"

def apply_hostname(new_hostname):
    with open(HOSTNAME_FILE, 'w') as f:
        f.write(new_hostname + "\n")

    run_command(f"hostname {new_hostname}")

    # avahi only re-announces its mDNS record on process start, not on
    # "reload" (that just re-reads static service files) - so it needs a
    # real stop/start to pick up the new kernel hostname without a reboot.
    run_command("/etc/init.d/S50avahi-daemon stop")
    time.sleep(1)
    run_command("/etc/init.d/S50avahi-daemon start")

# -----------------------
# System stats (CPU / RAM / Disk / Temp)
# -----------------------
def get_cpu_percent():
    """CPU usage in % since the last call, based on /proc/stat deltas."""
    global _last_cpu_sample
    try:
        with open('/proc/stat') as f:
            line = f.readline()
        values = [int(v) for v in line.split()[1:]]
        idle = values[3] + values[4]  # idle + iowait
        total = sum(values)

        prev_total = _last_cpu_sample['total']
        prev_idle = _last_cpu_sample['idle']
        _last_cpu_sample = {'total': total, 'idle': idle}

        if prev_total is None:
            return 0.0

        dt = total - prev_total
        di = idle - prev_idle
        if dt <= 0:
            return 0.0

        return round(max(0.0, min(100.0, (1 - di / dt) * 100)), 1)
    except Exception:
        return 0.0

def get_memory_info():
    try:
        meminfo = {}
        with open('/proc/meminfo') as f:
            for line in f:
                key, _, value = line.partition(':')
                meminfo[key] = int(value.strip().split()[0])  # kB

        total = meminfo.get('MemTotal', 0)
        available = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
        used = max(0, total - available)
        percent = round(used / total * 100, 1) if total else 0.0

        return {
            'total_mb': round(total / 1024, 1),
            'used_mb': round(used / 1024, 1),
            'percent': percent
        }
    except Exception:
        return {'total_mb': 0, 'used_mb': 0, 'percent': 0}

def get_disk_info(path='/'):
    try:
        usage = shutil.disk_usage(path)
        percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
        return {
            'total_gb': round(usage.total / (1024 ** 3), 2),
            'used_gb': round(usage.used / (1024 ** 3), 2),
            'percent': percent
        }
    except Exception:
        return {'total_gb': 0, 'used_gb': 0, 'percent': 0}

def get_cpu_temperature():
    try:
        with open(THERMAL_ZONE_PATH) as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None

def get_uptime_seconds():
    try:
        with open('/proc/uptime') as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0

def get_load_average():
    try:
        return os.getloadavg()
    except Exception:
        return (0.0, 0.0, 0.0)

# -----------------------
# Audio (ALSA mixer)
# -----------------------
def get_audio_controls():
    output = run_command("amixer scontrols")
    return re.findall(r"Simple mixer control '([^']+)'", output)

def get_audio_status(control):
    output = run_command(f"amixer sget {shlex.quote(control)}")
    percent_match = re.search(r'\[(\d+)%\]', output)
    percent = int(percent_match.group(1)) if percent_match else 0
    on_off = re.findall(r'\[(on|off)\]', output)
    muted = bool(on_off) and all(state == 'off' for state in on_off)
    return {'percent': percent, 'muted': muted, 'has_volume': percent_match is not None}

def apply_audio_volume(control, percent):
    run_command(f"amixer sset {shlex.quote(control)} {int(percent)}%")

def apply_audio_mute(control, muted):
    if get_audio_status(control)['muted'] != muted:
        run_command(f"amixer sset {shlex.quote(control)} toggle")

def save_audio_config(control, percent, muted):
    try:
        with open(AUDIO_CONFIG_PATH, 'w') as f:
            json.dump({'control': control, 'percent': percent, 'muted': muted}, f)
    except Exception as e:
        print(f"[ERROR] Could not save audio config: {e}")

def load_audio_config():
    try:
        with open(AUDIO_CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return None

# -----------------------
# MediaMTX API
# -----------------------

def filter_config_by_prefix(data, prefix="rpi"):
    if not isinstance(data, dict):
        return data

    filtered = {}
    lower_prefix = prefix.lower()

    for key, value in data.items():
        key_str = str(key)

        if key_str.lower().startswith(lower_prefix):
            if isinstance(value, dict):
                filtered[key] = filter_config_by_prefix(value, prefix)
            else:
                filtered[key] = value

        elif isinstance(value, dict):
            filtered_value = filter_config_by_prefix(value, prefix)
            if filtered_value:
                 filtered[key] = filtered_value

        elif isinstance(value, list):
            filtered[key] = value

    return filtered

def fetch_mediamtx_config():
    result = {
        'path_cam': {'error': None}
    }

    try:
        path_url = f"{MEDIAMTX_API_HOST}/v3/config/paths/get/cam"
        r = requests.get(path_url, timeout=3)
        r.raise_for_status()

        payload = r.json()
        if isinstance(payload, dict) and 'item' in payload:
            result['path_cam'] = payload.get('item', {})
        else:
            result['path_cam'] = payload

        if 'error' in result['path_cam']:
            del result['path_cam']['error']

    except requests.exceptions.RequestException as e:
        result['path_cam'] = {"error": f"Error getting 'cam' config: {e}"}

    return result


# -----------------------
# Functions: dict -> HTML (rekursiv)
# -----------------------
def format_dict_for_html(data):
    if data is None or (isinstance(data, dict) and not data):
        return '<span class="config-value text-gray-400">No Data / null</span>'

    if isinstance(data, dict):
        html = '<ul class="config-list">'
        for key, value in data.items():
            html += '<li class="config-item">'
            html += f'<span class="config-key">{str(key)}:</span> '
            if isinstance(value, (dict, list)):
                html += format_dict_for_html(value)
            else:
                html += f'<span class="config-value">{str(value)}</span>'
            html += '</li>'
        html += '</ul>'
        return html

    if isinstance(data, list):
        html = '<ul class="config-array">'
        for item in data:
            html += '<li class="config-item">'
            if isinstance(item, (dict, list)):
                html += format_dict_for_html(item)
            else:
                html += f'<span class="config-value">{str(item)}</span>'
            html += '</li>'
        html += '</ul>'
        return html

    return f'<span class="config-value">{str(data)}</span>'

app.jinja_env.globals.update(format_dict_for_html=format_dict_for_html)

@app.route('/api/mediamtx/tuning-files', methods=['GET'])
def list_tuning_files():
    try:
        if not os.path.isdir(TUNING_FILES_DIR):
            return jsonify({'files': []})
        files = sorted(f for f in os.listdir(TUNING_FILES_DIR) if f.endswith('.json'))
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'files': [], 'error': str(e)}), 500

@app.route('/api/mediamtx/cam', methods=['PATCH'])
@basic_auth_required
def patch_mediamtx_cam_path_config():
    """Proxies the PATCH request to MediaMTX's 'cam' path config set endpoint."""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({"status": "error", "error": "No JSON data provided"}), 400
        target_url = f"{MEDIAMTX_API_HOST}/v3/config/paths/patch/cam"

        response = requests.patch(target_url, json=data, timeout=5)
        if response.status_code == 200:
            return jsonify({"status": "success", "message": "'cam' Path-config saved."}), 200
        else:
            try:
                error_message = response.json().get('error', f"MediaMTX responded with status code {response.status_code}")
            except json.JSONDecodeError:
                error_message = f"MediaMTX responded with status code {response.status_code} and non-JSON content: {response.text[:100]}..."

            return jsonify({"status": "error", "error": error_message, "details": response.text}), response.status_code

    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "error": f"Connectionerror to MediaMTX API {MEDIAMTX_API_HOST}"}), 503
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# -----------------------
# API-Endpoint (WLAN, System)
# -----------------------
@app.route('/api/scan', methods=['GET'])
def scan_wifi():
    scan_trigger = run_command("wpa_cli -i wlan0 scan")

    if "OK" not in scan_trigger:
        return jsonify({
            'status': 'error',
            'message': 'Scan failed. Interface might be busy or in AP mode.'
        }), 500

    time.sleep(1)

    raw_results = run_command("wpa_cli -i wlan0 scan_results")

    networks = []
    lines = raw_results.splitlines()

    # Skip the first two lines (header and separator)
    for line in lines[2:]:
        parts = line.split('\t')
        if len(parts) >= 5:
            ssid = parts[4].strip()
            # Avoid empty SSIDs (hidden networks) and duplicates
            if ssid and ssid not in networks:
                networks.append(ssid)

    return jsonify({'networks': networks})

@app.route('/api/wifi', methods=['POST'])
def connect_wifi():
    data = request.json or {}
    ssid = data.get('ssid')
    password = data.get('password', '')

    if not ssid:
        return jsonify({'status': 'error', 'message': 'SSID missing'}), 400

    try:
        print(f"[WIFI] Started add_wifi.sh for SSID: {ssid}")
        os.system(f"/opt/webadmin/add_wifi.sh {ssid} {password} &")

        return jsonify({
            'status': 'success',
            'message': f'Connection attempt to {ssid} started. If it fails, the hotspot will return in 30 seconds.'
        })

    except Exception as e:
        print(f"[ERROR] Failed to start wifi script: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/hostname', methods=['POST'])
def set_hostname():
    data = request.json or {}
    new_hostname = data.get('hostname', '').strip()

    if not new_hostname or not HOSTNAME_RE.match(new_hostname):
        return jsonify({
            'status': 'error',
            'message': 'Invalid hostname. Use only letters, digits and hyphens (max 63 characters, no leading/trailing hyphen).'
        }), 400

    try:
        apply_hostname(new_hostname)
        return jsonify({
            'status': 'success',
            'message': f'Hostname set to "{new_hostname}". Reachable as {new_hostname}.local shortly.'
        })
    except Exception as e:
        print(f"[ERROR] Failed to set hostname: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/system', methods=['POST'])
def system_control():
    action = (request.json or {}).get('action', '')
    if action == 'reboot':
        try:
            os.system("/sbin/reboot &")
            return jsonify({'status': 'Rebooting...'})
        except Exception as e:
            print(f"[ERROR] Failed to reboot system: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    elif action == 'poweroff':
        try:
            os.system("/sbin/poweroff &")
            return jsonify({'status': 'Shutting down...'})
        except Exception as e:
            print(f"[ERROR] Failed to sshuttdown system: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({'status': 'Unknown command'}), 400

@app.route('/api/system/stream', methods=['GET'])
@basic_auth_required
def system_stream():
    action = request.args.get('action', '')  # GET-Parameter statt JSON
    commands = {
        "update_mediamtx": "/opt/webadmin/update_mediamtx.sh",
        "update_webserver": "/opt/webadmin/update_webserver.sh",
        "sync_os_files": "python3 -u /opt/webadmin/update_os_files.py",
        "setup_tailscale": "tailscale up",
        "restart_cameraserver": "/etc/init.d/S99start_mediamtx restart",
        "restart_webserver": "/etc/init.d/S99webadmin restart"
    }

    if action == "show_MTX_changes":
        def generate_diff():
            new_file = MEDIAMTX_CONFIG_PATH + ".new"
            if not os.path.exists(new_file):
                yield f"data: Error: No file to compare found -> {new_file}\n\n"
            else:
                # Wir leiten print() direkt in den SSE-Stream um
                class StreamCapturer:
                    def write(self, text):
                        if text.strip():
                            for line in text.splitlines():
                                yield_queue.append(line)
                    def flush(self):
                        pass

                yield_queue = []

                import io
                import sys

                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    compare_and_print_config_changes(MEDIAMTX_CONFIG_PATH, new_file)
                    output = sys.stdout.getvalue()
                finally:
                    sys.stdout = old_stdout

                for line in output.splitlines():
                    yield f"data: {line}\n\n"

            yield "data: --- DONE ---\n\n"

        return Response(generate_diff(), mimetype='text/event-stream')

    if action not in commands:
        return "event: message\ndata: Unknown action\n\n", 400

    cmd = commands[action]

    def generate():
        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            for line in process.stdout:
                yield f"data: {line.rstrip()}\n\n"
                print(f"data: {line.rstrip()}\n\n")
            process.wait()
            yield "data: --- DONE ---\n\n"
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/audio/controls', methods=['GET'])
def api_audio_controls():
    try:
        return jsonify({'controls': get_audio_controls()})
    except Exception as e:
        return jsonify({'controls': [], 'error': str(e)}), 500

@app.route('/api/audio/status', methods=['GET'])
def api_audio_status():
    control = request.args.get('control', '')
    if not control or control not in get_audio_controls():
        return jsonify({'error': 'Unknown audio control'}), 404
    try:
        return jsonify(get_audio_status(control))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/audio/volume', methods=['POST'])
def api_audio_volume():
    data = request.get_json() or {}
    control = data.get('control', '')
    percent = data.get('percent')

    if not control or control not in get_audio_controls():
        return jsonify({'status': 'error', 'message': 'Unknown audio control'}), 404
    if not isinstance(percent, int) or not (0 <= percent <= 100):
        return jsonify({'status': 'error', 'message': 'percent must be an integer between 0 and 100'}), 400
    if not get_audio_status(control)['has_volume']:
        return jsonify({'status': 'error', 'message': f'"{control}" has no volume control, only on/off'}), 400

    try:
        apply_audio_volume(control, percent)
        status = get_audio_status(control)
        save_audio_config(control, percent, status['muted'])
        return jsonify({'status': 'success', 'message': f'Volume set to {percent}%'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/audio/mute', methods=['POST'])
def api_audio_mute():
    data = request.get_json() or {}
    control = data.get('control', '')
    muted = data.get('muted')

    if not control or control not in get_audio_controls():
        return jsonify({'status': 'error', 'message': 'Unknown audio control'}), 404
    if not isinstance(muted, bool):
        return jsonify({'status': 'error', 'message': 'muted must be a boolean'}), 400

    try:
        apply_audio_mute(control, muted)
        status = get_audio_status(control)
        save_audio_config(control, status['percent'], muted)
        return jsonify({'status': 'success', 'message': 'Mute updated' if muted else 'Unmuted'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/system/stats', methods=['GET'])
def system_stats():
    load1, load5, load15 = get_load_average()
    return jsonify({
        'cpu_percent': get_cpu_percent(),
        'cpu_count': os.cpu_count() or 1,
        'memory': get_memory_info(),
        'disk': get_disk_info(),
        'temperature_c': get_cpu_temperature(),
        'load_average': {
            '1min': round(load1, 2),
            '5min': round(load5, 2),
            '15min': round(load15, 2)
        },
        'uptime_seconds': get_uptime_seconds()
    })

@app.route('/api/logs/stream', methods=['GET'])
@basic_auth_required
def logs_stream():
    source = request.args.get('source', 'webadmin')
    log_path = LOG_SOURCES.get(source)

    if not log_path:
        return "event: message\ndata: Unknown log source\n\n", 400

    def generate():
        if not os.path.exists(log_path):
            yield f"data: [Log file not found: {log_path}]\n\n"
            return

        process = subprocess.Popen(
            ["tail", "-n", "200", "-F", log_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        try:
            for line in process.stdout:
                yield f"data: {line.rstrip()}\n\n"
        finally:
            process.kill()

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/version', methods=['GET'])
def get_version():
    version_file = '/etc/babycam-version'
    data = {
        'version': 'unknown',
        'full_build': 'unknown',
        'build_date': 'unknown',
        'webserver_version': 'unknown',
        'mediamtx_version': 'unknown'
    }

    if not os.path.exists(version_file):
        return jsonify({
            'status': 'error',
            'message': 'Version information not found on system'
        }), 404

    try:
        with open(version_file, 'r') as f:
            for line in f:
                # Split 'KEY=VALUE' into key and value
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    if key == 'VERSION':
                        data['version'] = value
                        data['webserver_version'] = value
                    elif key == 'FULL_BUILD':
                        data['full_build'] = value
                    elif key == 'BUILD_DATE':
                        data['build_date'] = value
                    elif key == 'WEBSERVER_VERSION':
                        data['webserver_version'] = value
                    elif key == 'MEDIAMTX_VERSION':
                        data['mediamtx_version'] = value

        return jsonify(data)

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Failed to read version file: {str(e)}'
        }), 500

@app.route('/api/auth_user', methods=['POST'])
@basic_auth_required
def api_auth_user():
    data = request.json or {}
    user = data.get('user', '').strip()
    password = data.get('password', '').strip()

    if not user:
        return jsonify({'error': 'Username required'}), 400

    try:
        cmd = ["/opt/webadmin/update_mediamtx_auth.sh", user, password]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return jsonify({'message': 'Credentials updated successfully'})
        else:
            return jsonify({'error': result.stderr or 'Script failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_config_file')
@basic_auth_required
def get_config_file():
    if not os.path.exists(MEDIAMTX_CONFIG_PATH):
        return "Datei nicht gefunden", 404
    with open(MEDIAMTX_CONFIG_PATH, 'r') as f:
        content = f.read()
    return content

@app.route('/api/save_config_file', methods=['POST'])
@basic_auth_required
def save_config_file():
    data = request.get_json()
    content = data.get('content')
    try:
        # Sicherheits-Backup erstellen
        os.system(f'cp {MEDIAMTX_CONFIG_PATH} {MEDIAMTX_CONFIG_PATH}.bak')

        with open(MEDIAMTX_CONFIG_PATH, 'w') as f:
            f.write(content)
        return jsonify({"status": "success", "message": "Gespeichert!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def write_mediamtx_yaml_key(key, value):
    """Replaces a single `key:` line in mediamtx.yml in-place (with backup)."""
    if not os.path.exists(MEDIAMTX_CONFIG_PATH):
        raise FileNotFoundError(f"{MEDIAMTX_CONFIG_PATH} not found")

    with open(MEDIAMTX_CONFIG_PATH, 'r') as f:
        content = f.read()

    new_content, count = re.subn(
        rf'^(\s*{re.escape(key)}:).*$',
        lambda m: m.group(1) + (f' {value}' if value else ''),
        content,
        count=1,
        flags=re.MULTILINE
    )

    if count == 0:
        raise KeyError(f"{key} key not found in mediamtx.yml")

    os.system(f'cp {MEDIAMTX_CONFIG_PATH} {MEDIAMTX_CONFIG_PATH}.bak')
    with open(MEDIAMTX_CONFIG_PATH, 'w') as f:
        f.write(new_content)

@app.route('/api/mediamtx/tuning-file', methods=['POST'])
@basic_auth_required
def set_tuning_file():
    """Writes rpiCameraTuningFile directly into mediamtx.yml (persistent)."""
    data = request.get_json() or {}
    tuning_file = data.get('tuning_file', '').strip()

    try:
        write_mediamtx_yaml_key('rpiCameraTuningFile', tuning_file)
        return jsonify({"status": "success", "message": "Tuning file saved to mediamtx.yml."})
    except (FileNotFoundError, KeyError) as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/mediamtx/roi', methods=['POST'])
@basic_auth_required
def set_roi():
    """Writes rpiCameraROI directly into mediamtx.yml (persistent)."""
    data = request.get_json() or {}
    roi = data.get('roi', '').strip()

    if roi:
        parts = roi.split(',')
        if len(parts) != 4 or not all(re.match(r'^-?\d+(\.\d+)?$', p) for p in parts):
            return jsonify({"status": "error", "message": "ROI must be in format x,y,width,height"}), 400

    try:
        write_mediamtx_yaml_key('rpiCameraROI', roi)
        return jsonify({"status": "success", "message": "Crop saved to mediamtx.yml."})
    except (FileNotFoundError, KeyError) as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# -----------------------
# HTML-Sites
# -----------------------
@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    if request.method == 'POST':
        new_postfix = request.form.get('stream_postfix', '').strip()
        if not new_postfix.startswith('/'):
            new_postfix = '/' + new_postfix

        try:
            with open(CONFIG_FILE_PATH, 'w') as f:
                f.write(new_postfix + "\n")
        except Exception as e:
            print("Error saving:", e)
            return f"Error saving: {e}", 500

        return redirect(url_for('settings_page'))

    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            stream_postfix = f.read().strip() or "/cam"
    except:
        stream_postfix = "/cam"

    # --- MediaMTX Config ---
    mediamtx_config_full = fetch_mediamtx_config()
    path_cam_full = mediamtx_config_full.get('path_cam', {})
    if not path_cam_full.get('error'):
        path_cam_filtered = filter_config_by_prefix(path_cam_full, RPI_PREFIX)
    else:
        path_cam_filtered = path_cam_full

    ip = get_ip_address()
    ssid = get_current_ssid()
    ip_tailscale = get_ip_tailscale_address()
    hostname = get_hostname()
    mediamtx_config = {'path_cam': path_cam_filtered}

    return render_template(
        'settings.html',
        ip=ip,
        ssid=ssid,
        ip_tailscale=ip_tailscale,
        hostname=hostname,
        stream_postfix=stream_postfix,
        mediamtx_config=mediamtx_config
    )

@app.route('/')
def stream_page():
    stream_postfix = "/cam"
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            stream_postfix = f.read().strip() or stream_postfix
    except FileNotFoundError:
        pass
    except Exception as e:
        print("Fehler beim Lesen des Stream-Postfix:", e)

    ip = get_ip_address()
    return render_template('stream.html', ip=ip, stream_postfix=stream_postfix)

# -----------------------
if __name__ == '__main__':
    os.environ['PATH'] = os.environ.get('PATH', '') + ':/sbin:/usr/sbin'

    saved_audio = load_audio_config()
    if saved_audio:
        try:
            apply_audio_volume(saved_audio['control'], saved_audio['percent'])
            apply_audio_mute(saved_audio['control'], saved_audio['muted'])
        except Exception as e:
            print(f"[WARN] Could not restore audio settings: {e}")

    try:
        app.run(host='0.0.0.0', port=80)
    except PermissionError:
        app.run(host='0.0.0.0', port=8000)
