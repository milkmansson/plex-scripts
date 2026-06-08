#!/usr/bin/env bash
# extract-all-subs.sh
# Recursively find all .mkv files under the current directory and extract
# every subtitle track from each, saving as <filename>.<lang>.<ext> alongside
# the source file.
#
# Requirements: mkvmerge, mkvextract (from MKVToolNix), jq

set -euo pipefail

# --- Argument parsing ---
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n)
            DRY_RUN=1
            ;;
        -h|--help)
            cat <<EOF
Usage: $(basename "$0") [--dry-run]

Recursively extract all subtitle tracks from every .mkv under the current
directory, saving each one alongside its source file as:
    <filename>.<lang>.<ext>            (first track of that language)
    <filename>.<n>.<lang>.<ext>        (2nd, 3rd, ... track of same language)

Options:
  -n, --dry-run    Show what would be extracted without writing any files.
  -h, --help       Show this help.
EOF
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

if [ "$DRY_RUN" -eq 1 ]; then
    echo "(dry-run mode: no files will be written)"
fi

# Map mkv subtitle codec_id -> file extension
codec_to_ext() {
    case "$1" in
        S_TEXT/UTF8|S_TEXT/ASCII)   echo "srt" ;;
        S_TEXT/ASS|S_TEXT/SSA)      echo "ass" ;;
        S_TEXT/WEBVTT)              echo "vtt" ;;
        S_HDMV/PGS)                 echo "sup" ;;
        S_VOBSUB)                   echo "sub" ;;  # also produces .idx
        S_TEXT/USF)                 echo "usf" ;;
        *)                          echo "sub" ;;  # fallback
    esac
}

# Normalise a language tag to a 2-letter code where possible.
# mkvmerge returns either ISO 639-2 (3-letter, e.g. "eng") in `language`
# or BCP-47 (e.g. "en", "pt-BR") in `language_ietf`. Prefer ietf if present.
lang_code() {
    local ietf="$1" iso3="$2"
    if [ -n "$ietf" ] && [ "$ietf" != "null" ] && [ "$ietf" != "und" ]; then
        # take the primary subtag (before any '-')
        echo "${ietf%%-*}"
        return
    fi
    # Fallback: minimal ISO 639-2 -> 639-1 mapping for common cases
    case "$iso3" in
        eng) echo "en" ;;
        spa) echo "es" ;;
        fre|fra) echo "fr" ;;
        ger|deu) echo "de" ;;
        ita) echo "it" ;;
        jpn) echo "ja" ;;
        chi|zho) echo "zh" ;;
        kor) echo "ko" ;;
        rus) echo "ru" ;;
        por) echo "pt" ;;
        dut|nld) echo "nl" ;;
        ara) echo "ar" ;;
        pol) echo "pl" ;;
        swe) echo "sv" ;;
        nor) echo "no" ;;
        dan) echo "da" ;;
        fin) echo "fi" ;;
        und|"") echo "und" ;;
        *)   echo "$iso3" ;;  # leave 3-letter if no mapping
    esac
}

extract_from_file() {
    local mkv="$1"
    local dir base
    dir="$(dirname "$mkv")"
    base="$(basename "${mkv%.mkv}")"

    echo ">> $mkv"

    # Get JSON identification
    local json
    if ! json="$(mkvmerge -J "$mkv" 2>/dev/null)"; then
        echo "   ! mkvmerge failed to read this file, skipping"
        return
    fi

    # Build a list of "id|codec_id|language|language_ietf|track_name" for subtitle tracks
    local rows
    rows="$(jq -r '
        .tracks[]
        | select(.type == "subtitles")
        | [
            .id,
            .properties.codec_id,
            (.properties.language // ""),
            (.properties.language_ietf // ""),
            (.properties.track_name // "")
          ]
        | @tsv
    ' <<<"$json")"

    if [ -z "$rows" ]; then
        echo "   (no subtitle tracks)"
        return
    fi

    # Track how many times we've seen each language code in this file,
    # so duplicate-language tracks get suffixed (.en, .en.2, .en.3 ...)
    declare -A seen
    while IFS=$'\t' read -r tid codec lang ietf tname; do
        local ext code outname count
        ext="$(codec_to_ext "$codec")"
        code="$(lang_code "$ietf" "$lang")"

        count="${seen[$code]:-0}"
        seen[$code]=$((count + 1))
        # Plex requires the language code to be the LAST token before the
        # extension. So for duplicates we put the disambiguator BEFORE the
        # language: <base>.<n>.<lang>.<ext> rather than <base>.<lang>.<n>.<ext>.
        if [ "$count" -eq 0 ]; then
            outname="${dir}/${base}.${code}.${ext}"
        else
            outname="${dir}/${base}.$((count + 1)).${code}.${ext}"
        fi

        echo "   track $tid ($codec, lang=$code) -> ${outname}"
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "      [dry-run] skipped"
        else
            mkvextract tracks "$mkv" "${tid}:${outname}" >/dev/null
        fi
    done <<<"$rows"
}

# Main loop: recurse from current dir, handle filenames with spaces/newlines safely
find . -type f -iname '*.mkv' -print0 \
    | while IFS= read -r -d '' f; do
        extract_from_file "$f"
      done

echo "Done."
