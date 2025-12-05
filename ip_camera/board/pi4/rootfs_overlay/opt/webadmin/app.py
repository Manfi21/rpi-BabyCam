import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
import subprocess
import os
import requests
import json
import time

app = Flask(__name__)

CONFIG_FILE_PATH = 'stream_postfix.txt'
MEDIAMTX_API_HOST= "http://127.0.0.1:9997"
RPI_PREFIX = "rpi"

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

def get_current_ssid():
    try:
        raw = run_command("iwctl station wlan0 show | grep 'Connected network' || true")
        if raw and "Connected network" in raw:
            parts = raw.split("Connected network")
            if len(parts) >= 2:
                return parts[-1].strip(" :\n\t")
    except Exception:
        pass
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
# API-Endpunkte (WLAN, System)
# -----------------------
@app.route('/api/scan', methods=['GET'])
def scan_wifi():
    scan_result = run_command("iwctl station wlan0 scan")

    if "failed" in scan_result.lower() or "not available" in scan_result.lower():
        return jsonify({'status': 'error', 'message': 'Scan failed. No Wifi or in AP mode.'}), 500

    command = (
        "iwctl station wlan0 get-networks 2>/dev/null "
        "| sed 's/\x1b\[[0-9;]*m//g' "
        "| awk 'NR>3 && !($0 ~ /----/) {print $0}' || true"
    )

    raw_output_networks = run_command(command)

    networks = []
    lines = raw_output_networks.splitlines()

    security_keywords = ['psk', 'open', '8021x', 'unsecured']

    for line in lines:
        if not line.strip():
            continue

        potential_ssid = line.strip()
        min_index = len(line)
        found_token = None

        for token in security_keywords:
            index = line.lower().find(token)
            if index != -1 and index < min_index:
                min_index = index
                found_token = token

        if found_token:
            potential_ssid = line[:min_index].strip()
        else:
            potential_ssid = line[:40].strip()

        if potential_ssid.startswith('>'):
            potential_ssid = potential_ssid[1:].strip()

        if potential_ssid.lower() in ['network', 'name', 'security', 'signal', 'psk', 'open', 'unsecured', '8021x']:
            continue

        if potential_ssid and potential_ssid not in networks:
            networks.append(potential_ssid)

    return jsonify({'networks': networks})

@app.route('/api/wifi', methods=['POST'])
def connect_wifi():
    data = request.json or {}
    ssid = data.get('ssid')
    password = data.get('password', '')

    if not ssid:
        return jsonify({'status': 'error', 'message': 'SSID fehlt'}), 400

    filename = f"/var/lib/iwd/{ssid}.psk"

    try:
        if not os.path.exists("/var/lib/iwd"):
             os.makedirs("/var/lib/iwd", exist_ok=True)
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error creating iwd-path: {str(e)}'}), 500

    try:
        if password:
            with open(filename, "w") as f:
                f.write(f"[Security]\nPassphrase={password}\n")

            print(run_command("/etc/init.d/S41wifi_ap_fallback stop"))
            print(run_command("/etc/init.d/S40iwd stop"))
            time.sleep(2)
            print(run_command("ip addr flush dev wlan0"))
            print(run_command("/etc/init.d/S40iwd start"))
            print(run_command("/etc/init.d/S40network restart", timeout=20))
            print(run_command("ip neigh flush all"))
            print(run_command("ifconfig wlan0 down"))
            print(run_command("ifconfig wlan0 up"))
            print("New Network set.")

        return jsonify({'status': 'success', 'message': f'Connecting to {ssid}.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/system', methods=['POST'])
def system_control():
    action = (request.json or {}).get('action', '')
    if action == 'reboot':
        try:
            os.system("/sbin/reboot &")
        except:
            pass
        return jsonify({'status': 'Rebooting...'})
    elif action == 'poweroff':
        try:
            os.system("/sbin/poweroff &")
        except:
            pass
        return jsonify({'status': 'Shutting down...'})
    return jsonify({'status': 'Unknown command'}), 400

@app.route('/api/system/stream', methods=['GET'])
def system_stream():
    action = request.args.get('action', '')  # GET-Parameter statt JSON
    commands = {
        "update_mediamtx": "/root/mediamtx --upgrade",
        "update_webserver": "echo 'update curl from github?'",
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
                # print(f"data: {line.rstrip()}\n\n")
            process.wait()
            yield "data: --- DONE ---\n\n"
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

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
    mediamtx_config = {'path_cam': path_cam_filtered}

    return render_template(
        'settings.html',
        ip=ip,
        ssid=ssid,
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
