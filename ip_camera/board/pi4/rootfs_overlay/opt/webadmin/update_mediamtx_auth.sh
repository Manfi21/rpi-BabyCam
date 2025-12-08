#!/bin/sh

# If username is "any", password is removed

USER_FILE="/root/auth_users.txt"
CONFIG="/root/mediamtx.yml"
BACKUP="/root/mediamtx.yml.bak"
USER="$1"
PASS="$2"

if [ -z "$USER" ]; then
    echo "Usage: $0 <username|'any'> [password]"
    exit 1
fi

echo "Checking if Mediamtx config exists..."
if [ ! -f "$CONFIG" ]; then
    echo "ERROR: $CONFIG not found!"
    exit 1
fi

echo "Creating backup..."
cp "$CONFIG" "$BACKUP"
echo "Backup saved to $BACKUP"

echo "==== Lines around authInternalUsers before update ===="
awk '/authInternalUsers:/ {p=1} p && NR<=p+40 {print} NR>p+40 {exit}' "$CONFIG"

echo "Updating normal user (first user block)..."
if [ "$USER" = "any" ]; then
    awk -v new_user="$USER" '
    BEGIN {replaced=0; inside=0}
    /- user:/ && replaced==0 {inside=1; replaced=1; print "- user: " new_user; next}
    inside && /^[[:space:]]*pass:/ {print "  pass:"; next}
    inside && /^[[:space:]]*-/ && !/pass:/ {inside=0}
    {print}
    ' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
else
    # Hashen
    USER_HASH=$(echo -n "$USER" | openssl dgst -binary -sha256 | openssl base64)
    PASS_HASH=$(echo -n "$PASS" | openssl dgst -binary -sha256 | openssl base64)

    awk -v new_user="$USER_HASH" -v new_pass="$PASS_HASH" '
    BEGIN {replaced=0; inside=0}
    /- user:/ && replaced==0 {inside=1; replaced=1; print "- user: sha256:" new_user; next}
    inside && /^[[:space:]]*pass:/ {print "  pass: sha256:" new_pass; next}
    inside && /^[[:space:]]*-/ && !/pass:/ {inside=0}
    {print}
    ' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
fi

echo "==== Lines around authInternalUsers after update ===="
awk '/authInternalUsers:/ {p=1} p && NR<=p+40 {print} NR>p+40 {exit}' "$CONFIG"

echo "Writing credentials to $USER_FILE ..."
if [ "$USER" = "any" ]; then
    echo "$USER:" > "$USER_FILE"
else
    echo "$USER_HASH:$PASS_HASH" > "$USER_FILE"
fi

echo "Done. Restart mediamtx to apply changes."
