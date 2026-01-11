#!/usr/bin/env bash

GIT_TAG=$(git describe --tags --abbrev=0)
GIT_TAG=${GIT_TAG:-"no-tag"}
DATE_STR=$(date +%Y_%m_%d)

BASE_NAME="${DATE_STR}_BabyCamOS_${GIT_TAG}"

echo "Starting packaging for Version: $GIT_TAG ($DATE_STR)"

# ---------------------------------------------------------
# Raspberry Pi Zero 2 W
# ---------------------------------------------------------
IMG_ZERO="build/pi0w2_babycam/images/sdcard.img"
NAME_ZERO="${BASE_NAME}_rpizero2w"

if [ -f "$IMG_ZERO" ]; then
    echo "Processing Pi Zero 2 W..."
    cp "$IMG_ZERO" "${NAME_ZERO}.img"
    tar -czvf "${NAME_ZERO}.tar.gz" "${NAME_ZERO}.img"
    rm "${NAME_ZERO}.img"
else
    echo "Warning: $IMG_ZERO not found!"
fi

# ---------------------------------------------------------
# Raspberry Pi 4
# ---------------------------------------------------------
IMG_PI4="build/pi4_babycam/images/sdcard.img"
NAME_PI4="${BASE_NAME}_rpi4"

if [ -f "$IMG_PI4" ]; then
    echo "Processing Pi 4..."
    cp "$IMG_PI4" "${NAME_PI4}.img"
    tar -czvf "${NAME_PI4}.tar.gz" "${NAME_PI4}.img"
    rm "${NAME_PI4}.img"
else
    echo "Warning: $IMG_PI4 not found!"
fi

echo "---------------------------------------"
echo "Done! Files created:"
ls -lh ${BASE_NAME}*
