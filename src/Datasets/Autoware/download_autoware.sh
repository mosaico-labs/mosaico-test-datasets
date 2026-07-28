#!/usr/bin/env bash
# download_autoware.sh
# Downloads the Autoware dataset files from Google Drive via curl.
#
# Usage: ./download_autoware.sh [dest_dir]
#
# dest_dir: optional path where files will be saved.
#           Defaults to ${HOME}/rosbags/Autoware
#           NOTE: "Autoware" is always appended to whatever path you provide.

set -euo pipefail

DEST_DIR="${1:-${HOME}/rosbags}/Autoware"

# ---------------------------------------------------------------------------
# Full file list (source: Google Drive folder)
# https://drive.google.com/drive/folders/1BMPcUhjq_BCLi521X88WpujoOiEi3_CJ
# ---------------------------------------------------------------------------
# Each entry maps a Google Drive file ID to its output filename.
declare -A FILES=(
    ["10tw3sBZzVAiu9gWbB4mMclGuzY2-86In"]="metadata.yaml"
    ["1uta5Xr_ftV4jERxPNVqooDvWerK0dn89"]="test_20240930_134039_0.db3"
)

# ---------------------------------------------------------------------------
# Helper: detect whether a downloaded file is actually an HTML page
# (warning / quota-exceeded / error) instead of real binary content.
# ---------------------------------------------------------------------------
looks_like_html() {
    local f="$1"
    head -c 512 "${f}" 2>/dev/null | grep -qiE '<!DOCTYPE html|<html' && return 0
    return 1
}

# ---------------------------------------------------------------------------
# Helper: download a (potentially large) file from Google Drive with curl,
# handling the "can't scan for viruses" confirmation step for large files.
#
# Google currently uses two different mechanisms depending on file size /
# account state:
#   1. Old style: drive.google.com/uc?export=download&confirm=TOKEN&id=ID
#   2. New style: the warning page contains a hidden HTML form that posts to
#      drive.usercontent.google.com/download with fields id/export/confirm/uuid
# This function tries the new style first, falls back to the old style, and
# finally verifies the result isn't itself an HTML page before declaring success.
# ---------------------------------------------------------------------------
gdrive_download() {
    local file_id="$1"
    local dest_file="$2"
    local cookie_jar warn_page
    cookie_jar="$(mktemp)"
    warn_page="$(mktemp)"

    # Step 1: hit the standard endpoint, capture cookies + body.
    curl -sc "${cookie_jar}" -L \
        "https://drive.google.com/uc?export=download&id=${file_id}" \
        -o "${warn_page}"

    if ! looks_like_html "${warn_page}"; then
        # Small file: the first response IS the file content.
        mv "${warn_page}" "${dest_file}"
        rm -f "${cookie_jar}" 2>/dev/null || true
        return 0
    fi

    # Step 2a: try to extract the new-style confirmation form fields.
    local uuid confirm
    uuid="$(grep -o 'name="uuid" value="[^"]*"' "${warn_page}" | head -n1 | sed 's/.*value="//;s/"$//' || true)"
    confirm="$(grep -o 'name="confirm" value="[^"]*"' "${warn_page}" | head -n1 | sed 's/.*value="//;s/"$//' || true)"

    if [[ -n "${uuid}" && -n "${confirm}" ]]; then
        curl -Lb "${cookie_jar}" \
            --continue-at - \
            --output "${dest_file}" \
            "https://drive.usercontent.google.com/download?id=${file_id}&export=download&confirm=${confirm}&uuid=${uuid}"
    else
        # Step 2b: fall back to old-style confirm token (plain "confirm=xxx" in body).
        local confirm_token
        confirm_token="$(grep -o 'confirm=[0-9A-Za-z_-]*' "${warn_page}" | head -n1 | cut -d'=' -f2 || true)"
        if [[ -n "${confirm_token}" ]]; then
            curl -Lb "${cookie_jar}" \
                --continue-at - \
                --output "${dest_file}" \
                "https://drive.google.com/uc?export=download&confirm=${confirm_token}&id=${file_id}"
        else
            echo "  [WARN] Could not find a confirmation token in Google's response." >&2
            rm -f "${cookie_jar}" "${warn_page}" 2>/dev/null || true
            return 1
        fi
    fi

    rm -f "${cookie_jar}" "${warn_page}" 2>/dev/null || true

    # Final sanity check: make sure we didn't just save another HTML page
    # (e.g. a "quota exceeded" or "can't verify" error instead of the file).
    if looks_like_html "${dest_file}"; then
        echo "  [WARN] Downloaded content looks like an HTML page, not the actual file." >&2
        echo "  [WARN] Google likely blocked the automated download (quota or size limit)." >&2
        return 1
    fi

    return 0
}

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
mkdir -p "${DEST_DIR}"
echo "Destination : ${DEST_DIR}"
echo "Files       : ${#FILES[@]}"
echo "-------------------------------------------"

FAILED=()

for file_id in "${!FILES[@]}"; do
    filename="${FILES[${file_id}]}"
    dest_file="${DEST_DIR}/${filename}"

    if [[ -f "${dest_file}" ]]; then
        echo "[SKIP]  ${filename} (already exists)"
        continue
    fi

    echo "[GET]   ${filename} (id: ${file_id})"
    if gdrive_download "${file_id}" "${dest_file}"; then
        echo "[OK]    ${dest_file}"
    else
        echo "[FAIL]  ${filename}" >&2
        FAILED+=("${filename}")
        rm -f "${dest_file}"
    fi
    echo ""
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "==========================================="
echo "Done. $(( ${#FILES[@]} - ${#FAILED[@]} )) / ${#FILES[@]} downloaded successfully."

if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "Failed:"
    for f in "${FAILED[@]}"; do echo "  - ${f}"; done
    exit 1
fi