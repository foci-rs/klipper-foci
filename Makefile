VERSION ?=
INDEX_URL ?=

.PHONY: installer FORCE
installer: build/klipper-foci-installer.sh

# FORCE makes the recipe re-run on every invocation regardless of file
# mtimes -- VERSION/INDEX_URL are make variables, not file dependencies, so
# without this a second `make installer VERSION=<new>` would report success
# while silently leaving the previous version's script in place.
build/klipper-foci-installer.sh: kpi.sh installer.sh deploy/klippy-extras/foci.py deploy/klippy-plugins/foci.py FORCE
	@test -n "$(VERSION)" || (echo "VERSION is required" >&2; exit 1)
	@test -n "$(INDEX_URL)" || (echo "INDEX_URL is required" >&2; exit 1)
	mkdir -p build
	{ \
	  cat kpi.sh; \
	  echo; \
	  cat installer.sh; \
	  echo; \
	  echo 'INSTALLER_VERSION="$(VERSION)"'; \
	  echo 'FOCI_INDEX_URL="$(INDEX_URL)"'; \
	  echo 'FOCI_SHIM_EXTRAS=$$(cat <<'"'"'FOCI_SHIM_EXTRAS_EOF'"'"''; \
	  cat deploy/klippy-extras/foci.py; \
	  echo 'FOCI_SHIM_EXTRAS_EOF'; \
	  echo ')'; \
	  echo 'FOCI_SHIM_PLUGINS=$$(cat <<'"'"'FOCI_SHIM_PLUGINS_EOF'"'"''; \
	  cat deploy/klippy-plugins/foci.py; \
	  echo 'FOCI_SHIM_PLUGINS_EOF'; \
	  echo ')'; \
	  echo 'foci_main "$$@"'; \
	} > build/klipper-foci-installer.sh
	chmod +x build/klipper-foci-installer.sh

FORCE:
