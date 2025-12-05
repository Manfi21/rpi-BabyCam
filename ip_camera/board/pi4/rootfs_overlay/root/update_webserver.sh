#!/bin/sh
# update_webserver.sh

REPO_USER="ManuFi21"
REPO_NAME="rpi-BabyCam"
BRANCH="main"
REMOTE_FOLDER="ip_camera/board/pi4/rootfs_overlay/opt/webadmin"
LOCAL_FOLDER="/opt/webadmin"
BACKUP_FOLDER="/opt/webadmin_backup"
TMP_TAR="/tmp/webadmin_update.tar.gz"
INIT_SCRIPT="/etc/init.d/S99webadmin"

# -----------------------------
# 1. Backup
# -----------------------------
echo "Create backup of webserver $BACKUP_FOLDER ..."
cp -r "$LOCAL_FOLDER" "$BACKUP_FOLDER" || {
    echo "Backup failed!"
    exit 1
}

# -----------------------------
# 2. tar.gz download from Github
# -----------------------------
TAR_URL="https://github.com/$REPO_USER/$REPO_NAME/archive/refs/heads/$BRANCH.tar.gz"
echo "Download tar.gz from $TAR_URL ..."
wget -O "$TMP_TAR" "$TAR_URL" || {
    echo "Download failed!"
    exit 1
}

# -----------------------------
# 3. Exctract
# -----------------------------
echo "Exctract $REMOTE_FOLDER to $LOCAL_FOLDER ..."
mkdir -p /tmp/webadmin_update
tar -xzf "$TMP_TAR" -C /tmp/webadmin_update || {
    echo "Exctract failed!"
    exit 1
}

SRC_PATH="/tmp/webadmin_update/$REPO_NAME-$BRANCH/$REMOTE_FOLDER"
if [ ! -d "$SRC_PATH" ]; then
    echo "Source $SRC_PATH does not exist!"
    exit 1
fi

cp -r "$SRC_PATH/"* "$LOCAL_FOLDER/" || {
    echo "Copy failed!"
    exit 1
}

rm -rf /tmp/webadmin_update
rm -f "$TMP_TAR"

# -----------------------------
# 4. Restsart webserver
# -----------------------------
echo "Restart webserver..."
if [ -x "$INIT_SCRIPT" ]; then
    "$INIT_SCRIPT" restart || {
        echo "Webserver restart failed!"
        exit 1
    }
else
    echo "Init-Skript $INIT_SCRIPT not found!"
    exit 1
fi

echo "Update successfull!"
exit 0
