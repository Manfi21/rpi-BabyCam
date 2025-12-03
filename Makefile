# Load previous project configuration if available
-include .project_config

.project_config: ;

export BR2_EXTERNAL += $(realpath ip_camera)
export BR2_GLOBAL_PATCH_DIR += $(realpath ip_camera/patches)

.DEFAULT_GOAL := all


ifneq ($(filter set-project-%,$(MAKECMDGOALS)),)
# continue
else
ifeq ($(strip $(EXTERNAL_BUILD_DIR)),)
$(error EXTERNAL_BUILD_DIR is not set! Please run 'make set-project-<name>' first.)
endif
endif


%:
	$(MAKE) -C buildroot O=../build/$(EXTERNAL_BUILD_DIR) $@

PHONY: set-project-%

set-project-%:
	@PROJECT=$*; \
	echo "Setting EXTERNAL_BUILD_DIR to '$$PROJECT'"; \
	{ \
		echo "EXTERNAL_BUILD_DIR := $$PROJECT"; \
	} > .project_config; \
	$(MAKE) -C buildroot O=../build/$$PROJECT $$PROJECT"_defconfig"

.PHONY: get-project
get-project:
	@echo "Getting project settins"
	@cat .project_config

.PHONY: clean-target
clean-target:
	@echo "Cleaning target"
	rm -rf build/$(EXTERNAL_BUILD_DIR)/target
	find build/$(EXTERNAL_BUILD_DIR)/ -name ".stamp_target_installed" -delete
	rm -f build/$(EXTERNAL_BUILD_DIR)/build/host-gcc-final-*/.stamp_host_installed
