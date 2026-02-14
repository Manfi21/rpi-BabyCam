#!/usr/bin/env bash

if [ -n "$1" ]; then
    NEW_TAG="$1"
    MSG="${2:-"Release $NEW_TAG"}"

    echo "Creating new Git tag: $NEW_TAG"
    git tag -a "$NEW_TAG" -m "$MSG"
    GIT_TAG="$NEW_TAG"
else
    GIT_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "no-tag")
fi

DATE_STR=$(date +%Y_%m_%d)
BASE_NAME="${DATE_STR}_BabyCamOS_${GIT_TAG}"

echo "Starting packaging for Version: $GIT_TAG ($DATE_STR)"

BOARDS=(
    "pi0w2_babycam|rpizero2w"
    "pi3_babycam|rpi3"
    "pi4_babycam|rpi4"
)

for entry in "${BOARDS[@]}"; do
    IFS="|" read -r BUILD_DIR SUFFIX <<< "$entry"

    IMG_PATH="build/${BUILD_DIR}/images/sdcard.img"
    OUT_NAME="${BASE_NAME}_${SUFFIX}"

    if [ -f "$IMG_PATH" ]; then
        echo "---------------------------------------"
        echo "Processing $SUFFIX..."

        make "set-project-${BUILD_DIR}"
        make

        cp "$IMG_PATH" "${OUT_NAME}.img"
        tar -czvf "${OUT_NAME}.tar.gz" "${OUT_NAME}.img"
        rm "${OUT_NAME}.img"
    else
        echo "Warning: $IMG_PATH not found!"
    fi
done

echo "---------------------------------------"
echo "Done! Files created:"
ls -lh ${BASE_NAME}*
