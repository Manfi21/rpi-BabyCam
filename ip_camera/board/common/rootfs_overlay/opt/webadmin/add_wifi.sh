#!/bin/sh
# Usage: ./add_wifi.sh "SSID" "PASSWORD"

NEW_SSID=$1
NEW_PASS=$2
WLAN_IF="wlan0"
WP_RUN="/var/run/wpa_supplicant"
WP_CONF="/etc/wpa_supplicant.conf"

echo "[WIFI] Starting connection process for: $NEW_SSID"

# 2. Cleanup existing wireless processes
echo "[WIFI] Cleaning up existing processes..."
killall hostapd dnsmasq wpa_supplicant 2>/dev/null
sleep 1
ip addr flush dev $WLAN_IF
ip link set $WLAN_IF up

# 3. Start wpa_supplicant in the background
echo "[WIFI] Starting wpa_supplicant..."
mkdir -p $WP_RUN
wpa_supplicant -B -i $WLAN_IF -c $WP_CONF

# Wait for the control socket to appear
MAX_RETRIES=5
COUNT=0
while [ ! -S "$WP_RUN/$WLAN_IF" ]; do
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "[ERROR] wpa_supplicant control socket not ready. Aborting."
        exit 1
    fi
    echo "Waiting for socket..."
    sleep 1
    COUNT=$((COUNT + 1))
done

# 4. Add the new network profile
ID=$(wpa_cli -i $WLAN_IF add_network)
if [ "$ID" = "FAIL" ] || [ -z "$ID" ]; then
    echo "[ERROR] Failed to add new network slot via wpa_cli."
    exit 1
fi

echo "[WIFI] Configuring network ID: $ID"
wpa_cli -i $WLAN_IF set_network $ID ssid "\"$NEW_SSID\""
wpa_cli -i $WLAN_IF set_network $ID psk "\"$NEW_PASS\""
wpa_cli -i $WLAN_IF set_network $ID key_mgmt WPA-PSK
wpa_cli -i $WLAN_IF enable_network $ID

# 5. Connection Verification Loop
echo "[WIFI] Attempting to connect to $NEW_SSID..."
SUCCESS=0
for i in $(seq 1 20); do
    STATUS=$(wpa_cli -i $WLAN_IF status)
    STATE=$(echo "$STATUS" | grep "wpa_state=" | cut -d= -f2)

    if [ "$STATE" = "COMPLETED" ]; then
        SUCCESS=1
        break
    fi
    echo "Current state: $STATE..."
    sleep 1
done

# 6. Finalization
if [ $SUCCESS -eq 1 ]; then
    echo "[SUCCESS] Connection established."

    # Save the configuration permanently
    SAVE_RES=$(wpa_cli -i $WLAN_IF save_config)
    if [ "$SAVE_RES" = "OK" ]; then
        echo "[WIFI] Configuration saved to $WP_CONF."
    else
        echo "[ERROR] Could not save configuration. Check file permissions."
    fi

    # Obtain an IP address
    echo "[WIFI] Requesting IP address via DHCP..."
    udhcpc -i $WLAN_IF -n -t 5
    sleep 1

    echo "[WIFI] Restarting MediaMTX camera server..."
    /etc/init.d/S99start_mediamtx restart
    exit 0
else
    echo "[FAILURE] Connection timed out. Removing temporary credentials."
    wpa_cli -i $WLAN_IF remove_network $ID
    wpa_cli -i $WLAN_IF save_config
    killall wpa_supplicant 2>/dev/null

    # Trigger the Access Point fallback script
    echo "[WIFI] Reverting to Access Point mode..."
    /etc/init.d/S41wifi start
    exit 1
fi
