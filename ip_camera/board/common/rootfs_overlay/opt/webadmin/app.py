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

app = Flask(__name__)

CONFIG_FILE_PATH = 'stream_postfix.txt'
MEDIAMTX_API_HOST= "http://127.0.0.1:9997"
RPI_PREFIX = "rpi"
USER_FILE = '/root/auth_users.txt'
MEDIAMTX_CONFIG_PATH = '/root/mediamtx.yml'

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
        "update_mediamtx": "/root/mediamtx --upgrade",
        "update_webserver": "/opt/webadmin/update_webserver.sh",
        "setup_tailscale": "tailscale up",
        "restart_cameraserver": "/etc/init.d/S99start_mediamtx restart",
        "restart_webserver": "/etc/init.d/S99webadmin restart"
    }

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

@app.route('/api/version', methods=['GET'])
def get_version():
    version_file = '/etc/babycam-version'
    data = {
        'version': 'unknown',
        'full_build': 'unknown',
        'build_date': 'unknown',
        'webserver_version': 'unknown'
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
    mediamtx_config = {'path_cam': path_cam_filtered}

    return render_template(
        'settings.html',
        ip=ip,
        ssid=ssid,
        ip_tailscale=ip_tailscale,
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
    try:
        app.run(host='0.0.0.0', port=80)
    except PermissionError:
        app.run(host='0.0.0.0', port=8000)
