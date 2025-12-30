#!/usr/bin/env bash

set -e

echo "cleaning not needed init scripts."

if [ -f "${TARGET_DIR}/etc/init.d/S80dnsmasq" ]; then \
    rm -f "${TARGET_DIR}/etc/init.d/S80dnsmasq"; \
fi

VERSION_FILE="${TARGET_DIR}/etc/babycam-version"
ISSUE_FILE="${TARGET_DIR}/etc/issue"

SCRIPT_DIR="$(dirname "$0")"

MAIN_REPO_DIR=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)

if [ -n "$MAIN_REPO_DIR" ]; then
    CLEAN_TAG=$(git -C "$MAIN_REPO_DIR" describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    FULL_VERSION=$(git -C "$MAIN_REPO_DIR" describe --tags --always --dirty 2>/dev/null || echo "v0.0.0-unknown")
else
    CLEAN_TAG="v0.0.0-error"
    FULL_VERSION="v0.0.0-repo-not-found"
fi

echo "VERSION=$CLEAN_TAG" > "$VERSION_FILE"
echo "FULL_BUILD=$FULL_VERSION" >> "$VERSION_FILE"
echo "BUILD_DATE=$(date +'%Y-%m-%d %H:%M')" >> "$VERSION_FILE"

echo "--------------------------------------------------" > "$ISSUE_FILE"
echo "  BabyCamOS" >> "$ISSUE_FILE"
echo "  Version: $CLEAN_TAG" >> "$ISSUE_FILE"
echo "  Build:   $FULL_VERSION" >> "$ISSUE_FILE"
echo "  Date:    $(date +'%Y-%m-%d %H:%M')" >> "$ISSUE_FILE"
echo "--------------------------------------------------" >> "$ISSUE_FILE"
echo "" >> "$ISSUE_FILE"

echo "[POST-BUILD] Versioning applied from Main Repo: $CLEAN_TAG"
