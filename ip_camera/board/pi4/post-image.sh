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

if [ ! -e "${GENIMAGE_CFG}" ]; then
	GENIMAGE_CFG="${BINARIES_DIR}/genimage.cfg"
	FILES=()

	for i in "${BINARIES_DIR}"/*.dtb "${BINARIES_DIR}"/rpi-firmware/*; do
		FILES+=( "${i#${BINARIES_DIR}/}" )
	done

	KERNEL=$(sed -n 's/^kernel=//p' "${BINARIES_DIR}/rpi-firmware/config.txt")
	FILES+=( "${KERNEL}" )

	BOOT_FILES=$(printf '\\t\\t\\t"%s",\\n' "${FILES[@]}")
	sed "s|#BOOT_FILES#|${BOOT_FILES}|" "${BOARD_DIR}/genimage.cfg.in" \
		> "${GENIMAGE_CFG}"
fi

cp $BR2_EXTERNAL_IP_CAMERA_PATH/board/${BOARD_NAME}/config.txt ${BINARIES_DIR}/rpi-firmware/
cp $BR2_EXTERNAL_IP_CAMERA_PATH/board/${BOARD_NAME}/cmdline.txt ${BINARIES_DIR}/rpi-firmware/

trap 'rm -rf "${ROOTPATH_TMP}"' EXIT
ROOTPATH_TMP="$(mktemp -d)"

rm -rf "${GENIMAGE_TMP}"

genimage \
	--rootpath "${ROOTPATH_TMP}"   \
	--tmppath "${GENIMAGE_TMP}"    \
	--inputpath "${BINARIES_DIR}"  \
	--outputpath "${BINARIES_DIR}" \
	--config "${GENIMAGE_CFG}"

exit $?
