#!/bin/sh
# update_webserver.sh

REPO_USER="Manfi21"
REPO_NAME="rpi-BabyCam"
API_URL="https://api.github.com/repos/$REPO_USER/$REPO_NAME/releases/latest"
REMOTE_FOLDER="ip_camera/board/common/rootfs_overlay/opt/webadmin"
LOCAL_FOLDER="/opt/webadmin"
BACKUP_FOLDER="/opt/webadmin_backup"
TMP_TAR="/tmp/webadmin_update.tar.gz"
INIT_SCRIPT="/etc/init.d/S99webadmin"
VERSION_FILE="/etc/babycam-version"

# -----------------------------
# 1. Backup
# -----------------------------
tailscale down
echo "Create backup of webserver $BACKUP_FOLDER ..."
cp -r "$LOCAL_FOLDER" "$BACKUP_FOLDER" || {
    echo "Backup failed!"
    tailscale up
    exit 1
}

echo "Fetching latest version info..."
LATEST_TAG=$(wget -qO- --header="User-Agent: Mozilla/5.0" "$API_URL" | grep -m 1 '"tag_name":' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
if [ -z "$LATEST_TAG" ]; then
    echo "Error: Could not retrieve latest tag."
    tailscale up
    exit 1
fi

echo "Latest version is: $LATEST_TAG"
NEW_LINE="WEBSERVER_VERSION=$LATEST_TAG"
if grep -q "^WEBSERVER_VERSION=" "$VERSION_FILE"; then
    echo "Updating existing version line..."
    sed "s/^WEBSERVER_VERSION=.*/$NEW_LINE/" "$VERSION_FILE" > "${VERSION_FILE}.tmp" && mv "${VERSION_FILE}.tmp" "$VERSION_FILE"
else
    echo "Adding new version line..."
    echo "$NEW_LINE" >> "$VERSION_FILE"
fi

# -----------------------------
# 2. tar.gz download from Github
# -----------------------------
TAR_URL="https://github.com/$REPO_USER/$REPO_NAME/archive/refs/tags/$LATEST_TAG.tar.gz"
echo "Downloading $TAR_URL ..."
wget -qO "$TMP_TAR" "$TAR_URL" || {
    echo "Download failed!"
    tailscale up
    exit 1
}

# -----------------------------
# 3. Exctract
# -----------------------------
echo "Exctract $REMOTE_FOLDER to $LOCAL_FOLDER ..."
mkdir -p /tmp/webadmin_update
tar -xzf "$TMP_TAR" -C /tmp/webadmin_update || {
    echo "Exctract failed!"
    tailscale up
    exit 1
}

SRC_PATH=$(ls -d /tmp/webadmin_update/$REPO_NAME-*)
FINAL_SRC="$SRC_PATH/$REMOTE_FOLDER"

if [ -d "$FINAL_SRC" ]; then
    echo "Updating files in $LOCAL_FOLDER ..."
    cp -r "$FINAL_SRC/"* "$LOCAL_FOLDER/"
    echo "Update to $LATEST_TAG finished."
else
    echo "Directory structure in ZIP changed! Check $REMOTE_FOLDER"
    tailscale up
    exit 1
fi

rm -rf /tmp/webadmin_update
rm -f "$TMP_TAR"

# -----------------------------
# 4. Restsart webserver
# -----------------------------
echo "Restart webserver..."
if [ -x "$INIT_SCRIPT" ]; then
    "$INIT_SCRIPT" restart || {
        echo "Webserver restart failed!"
        tailscale up
        exit 1
    }
else
    echo "Init-Skript $INIT_SCRIPT not found!"
    tailscale up
    exit 1
fi

echo "Update successfull!"
tailscale up
exit 0
