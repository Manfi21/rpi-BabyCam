################################################################################
#
# mediamtx Buildroot package
# Downloads prebuilt standalone binary from GitHub releases and installs it
#
################################################################################

MEDIAMTX_VERSION = 1.15.4
MEDIAMTX_SITE = https://github.com/bluenviron/mediamtx/releases/download/v$(MEDIAMTX_VERSION)
MEDIAMTX_SOURCE = mediamtx_v$(MEDIAMTX_VERSION)_linux_arm64.tar.gz
MEDIAMTX_LICENSE = MIT
MEDIAMTX_LICENSE_FILES = LICENSE
MEDIAMTX_HASH = $(BR2_EXTERNAL_IP_CAMERA_PATH)/package/mediamtx/mediamtx.hash

MEDIAMTX_BUILD_DIR = $(BUILD_DIR)/mediamtx-$(MEDIAMTX_VERSION)

define MEDIAMTX_EXTRACT_CMDS
	tar -xzf $(DL_DIR)/mediamtx/$(MEDIAMTX_SOURCE) -C $(MEDIAMTX_BUILD_DIR)
endef

define MEDIAMTX_INSTALL_TARGET_CMDS
	# Nur die Binary ins Target kopieren
	$(INSTALL) -D $(MEDIAMTX_BUILD_DIR)/mediamtx $(TARGET_DIR)/root/mediamtx
endef

$(eval $(generic-package))
