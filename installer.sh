#!/usr/bin/env bash
# installer.sh — klipper-foci printer-side install logic.
# Sourced after kpi.sh by the generated installer; not run standalone.

foci_resolve_venv() {
    local python_path="$1"
    dirname "$(dirname "$python_path")"
}

foci_write_pip_conf() {
    local venv_root="$1" index_url="$2" force=""
    [ "${3:-}" = "--force" ] && force=1
    local conf="$venv_root/pip.conf"
    mkdir -p "$venv_root"

    if [ ! -f "$conf" ]; then
        printf '[global]\nindex-url = %s\n' "$index_url" > "$conf"
        return 0
    fi

    local existing_index has_extra
    existing_index="$(grep -E '^index-url' "$conf" | head -1 | sed 's/^index-url *= *//')"
    has_extra=0
    grep -qE '^extra-index-url' "$conf" && has_extra=1

    if [ -n "$existing_index" ] && [ "$existing_index" != "$index_url" ] && [ -z "$force" ]; then
        log "pip.conf at $conf already sets a different index-url ($existing_index)." >&2
        log "Remove it manually and re-run, or pass --force." >&2
        return 1
    fi
    if [ "$has_extra" = "1" ] && [ -z "$force" ]; then
        log "pip.conf at $conf has an extra-index-url set; pass --force to remove it." >&2
        return 1
    fi
    if [ "$existing_index" = "$index_url" ] && [ "$has_extra" = "0" ]; then
        return 0
    fi

    backup_file "$conf"

    # Preserve every unrelated line (other settings, other sections); only
    # index-url/extra-index-url are touched, never the rest of the file.
    awk '!/^index-url/ && !/^extra-index-url/ { print }' "$conf" > "$conf.new"
    if grep -q '^\[global\]' "$conf.new"; then
        awk -v url="$index_url" '
            { print }
            /^\[global\]/ && !done { print "index-url = " url; done=1 }
        ' "$conf.new" > "$conf.new2"
        mv "$conf.new2" "$conf"
    else
        { echo "[global]"; echo "index-url = $index_url"; echo; cat "$conf.new"; } > "$conf"
    fi
    rm -f "$conf.new"
}

# backup_file: a single-file timestamped backup. The vendored kpi.sh only
# provides backup_dir_timestamped(), which requires a directory source and
# dies on anything else -- not usable for a single config file, so this
# small helper stays local to installer.sh instead.
backup_file() {
    local target="$1"
    cp "$target" "$target.bak.$(date +%s)"
}
