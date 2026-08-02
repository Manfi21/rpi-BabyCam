#!/bin/sh
# update_mediamtx.sh
#
# Updates /root/mediamtx to the latest GitHub release.
# mediamtx's own "--upgrade" flag resolves the latest version via the git
# smart-HTTP protocol against github.com, which has proven unreliable on
# this device. This script instead downloads the release tarball directly.

REPO_USER="bluenviron"
REPO_NAME="mediamtx"
API_URL="https://api.github.com/repos/$REPO_USER/$REPO_NAME/releases/latest"
ARCH="linux_arm64"
BIN_PATH="/root/mediamtx"
BACKUP_PATH="/root/mediamtx.bak"
TMP_TAR="/tmp/mediamtx_update.tar.gz"
TMP_EXTRACT="/tmp/mediamtx_update"
INIT_SCRIPT="/etc/init.d/S99start_mediamtx"
VERSION_FILE="/etc/babycam-version"

# Returns 0 if $1 >= $2 (dotted numeric versions, optional leading 'v').
version_ge() {
    awk -v a="$1" -v b="$2" '
        function score(v,   n, p, i, q, s) {
            gsub(/^[vV]/, "", v)
            n = split(v, p, ".")
            for (i = 1; i <= 3; i++) {
                q = p[i]
                sub(/[^0-9].*$/, "", q)
                q = (q == "" ? 0 : q + 0)
                s = s * 1000 + q
            }
            return s
        }
        BEGIN { exit (score(a) < score(b)) }'
}

# -----------------------------
# 1. Determine latest version
# -----------------------------
echo "Fetching latest mediamtx version info..."
LATEST_TAG=$(wget -qO- --header="User-Agent: Mozilla/5.0" "$API_URL" | grep -m 1 '"tag_name":' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
if [ -z "$LATEST_TAG" ]; then
    echo "Error: Could not retrieve latest tag."
    exit 1
fi
echo "Latest version is: $LATEST_TAG"

INSTALLED_VERSION=$(sed -n 's/^MEDIAMTX_VERSION=\(.*\)/\1/p' "$VERSION_FILE")
if [ -n "$INSTALLED_VERSION" ] && version_ge "$INSTALLED_VERSION" "$LATEST_TAG"; then
    echo "Already up to date (installed mediamtx $INSTALLED_VERSION, latest $LATEST_TAG). No update needed."
    exit 0
fi

# -----------------------------
# 2. Download release tarball
# -----------------------------
ASSET_NAME="mediamtx_${LATEST_TAG}_${ARCH}.tar.gz"
DOWNLOAD_URL="https://github.com/$REPO_USER/$REPO_NAME/releases/download/$LATEST_TAG/$ASSET_NAME"

echo "Downloading $DOWNLOAD_URL ..."
wget -qO "$TMP_TAR" "$DOWNLOAD_URL" || {
    echo "Download failed!"
    rm -f "$TMP_TAR"
    exit 1
}

echo "Extracting..."
rm -rf "$TMP_EXTRACT"
mkdir -p "$TMP_EXTRACT"
tar -xzf "$TMP_TAR" -C "$TMP_EXTRACT" mediamtx || {
    echo "Extract failed!"
    rm -rf "$TMP_EXTRACT" "$TMP_TAR"
    exit 1
}

# -----------------------------
# 3. Stop, swap binary, restart
# -----------------------------
echo "Stopping mediamtx..."
"$INIT_SCRIPT" stop

echo "Backing up current binary to $BACKUP_PATH ..."
cp "$BIN_PATH" "$BACKUP_PATH" || {
    echo "Backup failed!"
    exit 1
}

echo "Installing new binary..."
cp "$TMP_EXTRACT/mediamtx" "$BIN_PATH"
chmod +x "$BIN_PATH"

rm -rf "$TMP_EXTRACT"
rm -f "$TMP_TAR"

NEW_LINE="MEDIAMTX_VERSION=$LATEST_TAG"
if [ -f "$VERSION_FILE" ] && grep -q "^MEDIAMTX_VERSION=" "$VERSION_FILE"; then
    echo "Updating existing version line..."
    sed "s/^MEDIAMTX_VERSION=.*/$NEW_LINE/" "$VERSION_FILE" > "${VERSION_FILE}.tmp" && mv "${VERSION_FILE}.tmp" "$VERSION_FILE"
else
    echo "Adding new version line..."
    echo "$NEW_LINE" >> "$VERSION_FILE"
fi

echo "Starting mediamtx..."
"$INIT_SCRIPT" start

echo "Update to $LATEST_TAG finished."
exit 0
