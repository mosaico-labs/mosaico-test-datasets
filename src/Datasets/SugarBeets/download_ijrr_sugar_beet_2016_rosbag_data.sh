#!/usr/bin/env bash
# download_ijrr_sugar_beet_2016.sh
# Downloads up to 3 rosbags per day from the IJRR Sugar Beet 2016 dataset.
#
# Usage: ./download_ijrr_sugar_beet_2016.sh [dest_dir]
#
# dest_dir: optional path where bags will be saved.
#           Defaults to ${HOME}/rosbags/SugarBeets
 
set -euo pipefail
 
DEST_DIR="${1:-${HOME}/rosbags}/SugarBeets"
SERVER="http://www.ipb.uni-bonn.de/datasets_IJRR2017/rosbags"
MAX_PER_DAY=1
 
DAYS=(
    160420 160421 160422 160425 160426 160427 160428 160429
    160502 160503 160504 160505 160506 160509 160510 160511
    160512 160513 160517 160518 160519 160523 160527 160531
    160606 160610 160614
)
 
mkdir -p "${DEST_DIR}"
echo "Destination : ${DEST_DIR}"
echo "Max per day : ${MAX_PER_DAY}"
echo "-------------------------------------------"
 
FAILED=()
 
for day in "${DAYS[@]}"; do
    day_dir="${DEST_DIR}/${day}"
    mkdir -p "${day_dir}"
 
    echo "[LIST]  Fetching index for day ${day}..."
    # Scrape the directory listing and extract .bag filenames
    mapfile -t bags < <(
        wget -q --no-check-certificate -O - "${SERVER}/${day}/" \
        | grep -oP '(?<=href=")[^"]+\.bag' \
        | sort \
        | head -n "${MAX_PER_DAY}"
    )
 
    if [[ ${#bags[@]} -eq 0 ]]; then
        echo "[WARN]  No bags found for day ${day}, skipping."
        continue
    fi
 
    for filename in "${bags[@]}"; do
        dest_file="${day_dir}/${filename}"
 
        if [[ -f "${dest_file}" ]]; then
            echo "[SKIP]  ${day}/${filename} (already exists)"
            continue
        fi
 
        url="${SERVER}/${day}/${filename}"
        echo "[GET]   ${url}"
        if wget \
            --continue \
            --show-progress \
            --progress=bar:force \
            --no-check-certificate \
            --output-document="${dest_file}" \
            "${url}"; then
            echo "[OK]    ${dest_file}"
        else
            echo "[FAIL]  ${url}" >&2
            FAILED+=("${url}")
            rm -f "${dest_file}"
        fi
        echo ""
    done
done
 
echo "==========================================="
if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "Some downloads failed:"
    for f in "${FAILED[@]}"; do echo "  - ${f}"; done
    exit 1
else
    echo "All downloads completed successfully."
fi