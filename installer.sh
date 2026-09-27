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

FOCI_SHIM_MARKER="# foci-shim: klipper-foci (do not edit; managed by install.sh)"

foci_select_shim_variant() {
    case "$1" in
        */plugins) echo "plugins" ;;
        *) echo "extras" ;;
    esac
}

foci_write_shim() {
    local target="$1" content="$2" force=""
    [ "${3:-}" = "--force" ] && force=1

    if [ -f "$target" ]; then
        if [ "$(head -1 "$target")" != "$FOCI_SHIM_MARKER" ]; then
            if [ -z "$force" ]; then
                log "$target exists and is not a foci-managed shim." >&2
                log "Move it aside manually, or pass --force." >&2
                return 1
            fi
            backup_file "$target"
        fi
    fi

    mkdir -p "$(dirname "$target")"
    printf '%s\n' "$content" > "$target"
}

foci_write_moonraker_block() {
    local conf="$1" venv_root="$2" project_name="${3:-}"
    local marker_begin="# BEGIN foci-managed: update_manager klipper-foci"
    local marker_end="# END foci-managed: update_manager klipper-foci"

    # Require exactly one well-formed, correctly-ordered marker pair before
    # doing anything else. A `sed -n /begin/,/end/p` range with an
    # unterminated or duplicated marker silently spans to EOF or across
    # unrelated later content -- refuse instead of ever deleting on that
    # basis. This check never modifies the file.
    local begin_count end_count
    begin_count="$(grep -c "^$marker_begin\$" "$conf" 2>/dev/null || true)"
    begin_count="${begin_count:-0}"
    end_count="$(grep -c "^$marker_end\$" "$conf" 2>/dev/null || true)"
    end_count="${end_count:-0}"

    if [ "$begin_count" -gt 1 ] || [ "$end_count" -gt 1 ] || [ "$begin_count" != "$end_count" ]; then
        log "$conf has malformed foci-managed markers ($begin_count begin, $end_count end)." >&2
        log "Fix or remove them manually before re-running." >&2
        return 1
    fi

    local begin_line="" end_line=""
    if [ "$begin_count" = "1" ]; then
        begin_line="$(grep -n "^$marker_begin\$" "$conf" | head -1 | cut -d: -f1)"
        end_line="$(grep -n "^$marker_end\$" "$conf" | head -1 | cut -d: -f1)"
        if [ "$end_line" -le "$begin_line" ]; then
            log "$conf has the foci-managed end marker before its begin marker." >&2
            log "Fix or remove them manually before re-running." >&2
            return 1
        fi
    fi

    # Every occurrence of the section header must lie inside our own marked
    # block. A marker existing SOMEWHERE in the file is not proof that every
    # matching section is ours -- a second, unmarked section could sit
    # alongside it.
    local total_sections managed_sections
    total_sections="$(grep -c '^\[update_manager klipper-foci\]' "$conf" 2>/dev/null || true)"
    total_sections="${total_sections:-0}"
    managed_sections=0
    if [ "$begin_count" = "1" ]; then
        managed_sections="$(sed -n "${begin_line},${end_line}p" "$conf" \
            | grep -c '^\[update_manager klipper-foci\]' || true)"
        managed_sections="${managed_sections:-0}"
    fi

    if [ "$total_sections" != "$managed_sections" ]; then
        log "$conf already has an [update_manager klipper-foci] section we don't own." >&2
        log "Remove or rename it manually before re-running." >&2
        return 1
    fi

    # Rewrite (not skip) an existing well-formed marked block every run, so
    # a changed flag combination (e.g. adding --diagnostics later) actually
    # updates project_name instead of silently keeping the stale value.
    if [ "$begin_count" = "1" ]; then
        sed -i.bak "${begin_line},${end_line}d" "$conf" && rm -f "$conf.bak"
    fi

    {
        echo ""
        echo "$marker_begin"
        echo "[update_manager klipper-foci]"
        echo "type: python"
        echo "channel: stable"
        echo "virtualenv: $venv_root"
        [ -n "$project_name" ] && echo "project_name: $project_name"
        echo "managed_services: klipper"
        echo "$marker_end"
    } >> "$conf"
}
