#!/usr/bin/env bash

set -e

BOARD_DIR="$(dirname $0)"
echo ${BOARD_DIR}
BOARD_NAME="$(basename ${BOARD_DIR})"
GENIMAGE_CFG="${BOARD_DIR}/genimage-${BOARD_NAME}.cfg"
GENIMAGE_TMP="${BUILD_DIR}/genimage.tmp"

mkdir -p ${TARGET_DIR}/boot
if [ -f "${TARGET_DIR}/etc/init.d/S80dnsmasq" ]; then \
    rm -f "${TARGET_DIR}/etc/init.d/S80dnsmasq"; \
fi

cp $BR2_EXTERNAL_IP_CAMERA_PATH/board/${BOARD_NAME}/config.txt ${BINARIES_DIR}/rpi-firmware/
cp $BR2_EXTERNAL_IP_CAMERA_PATH/board/${BOARD_NAME}/cmdline.txt ${BINARIES_DIR}/rpi-firmware/

rm -rf "${GENIMAGE_TMP}"

genimage --rootpath "${TARGET_DIR}"     \
         --tmppath "${GENIMAGE_TMP}"    \
         --inputpath "${BINARIES_DIR}"  \
         --outputpath "${BINARIES_DIR}" \
         --config "${GENIMAGE_CFG}"
