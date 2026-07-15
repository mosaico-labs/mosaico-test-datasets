#!/usr/bin/env bash
# download_uzh_fpv.sh
# Downloads all UZH-FPV Dataset rosbags via wget.
#
# Usage: ./download_uzh_fpv.sh [dest_dir]
#
# dest_dir: optional path where bags will be saved.
#           Defaults to ${HOME}/rosbags/UZH-FPV

set -euo pipefail

DEST_DIR="${1:-${HOME}/rosbags}/UZH-FPV"

# ---------------------------------------------------------------------------
# Full bag list (source: https://fpv.ifi.uzh.ch/datasets/)
# ---------------------------------------------------------------------------
BASE="http://rpg.ifi.uzh.ch/datasets/uzh-fpv-newer-versions/v3"

BAGS=(
    # SplitS Track
    "https://download.ifi.uzh.ch/rpg/drone_racing_data/race_1.bag"
    "https://download.ifi.uzh.ch/rpg/drone_racing_data/race_2.bag"
    "https://download.ifi.uzh.ch/rpg/drone_racing_data/race_3.bag"

    # Indoor forward facing
    "${BASE}/indoor_forward_3_davis_with_gt.bag"
    "${BASE}/indoor_forward_3_snapdragon_with_gt.bag"
    "${BASE}/indoor_forward_5_davis_with_gt.bag"
    "${BASE}/indoor_forward_5_snapdragon_with_gt.bag"
    "${BASE}/indoor_forward_6_davis_with_gt.bag"
    "${BASE}/indoor_forward_6_snapdragon_with_gt.bag"
    "${BASE}/indoor_forward_7_davis_with_gt.bag"
    "${BASE}/indoor_forward_7_snapdragon_with_gt.bag"
    "${BASE}/indoor_forward_8_davis.bag"
    "${BASE}/indoor_forward_8_snapdragon.bag"
    "${BASE}/indoor_forward_9_davis_with_gt.bag"
    "${BASE}/indoor_forward_9_snapdragon_with_gt.bag"
    "${BASE}/indoor_forward_10_davis_with_gt.bag"
    "${BASE}/indoor_forward_10_snapdragon_with_gt.bag"
    "${BASE}/indoor_forward_11_davis.bag"
    "${BASE}/indoor_forward_11_snapdragon.bag"
    "${BASE}/indoor_forward_12_davis.bag"
    "${BASE}/indoor_forward_12_snapdragon.bag"

    # Indoor 45° downward facing
    "${BASE}/indoor_45_1_davis.bag"
    "${BASE}/indoor_45_1_snapdragon.bag"
    "${BASE}/indoor_45_2_davis_with_gt.bag"
    "${BASE}/indoor_45_2_snapdragon_with_gt.bag"
    "${BASE}/indoor_45_3_davis.bag"
    "${BASE}/indoor_45_3_snapdragon.bag"
    "${BASE}/indoor_45_4_davis_with_gt.bag"
    "${BASE}/indoor_45_4_snapdragon_with_gt.bag"
    "${BASE}/indoor_45_9_davis_with_gt.bag"
    "${BASE}/indoor_45_9_snapdragon_with_gt.bag"
    "${BASE}/indoor_45_11_davis.bag"
    "${BASE}/indoor_45_11_snapdragon.bag"
    "${BASE}/indoor_45_12_davis_with_gt.bag"
    "${BASE}/indoor_45_12_snapdragon_with_gt.bag"
    "${BASE}/indoor_45_13_davis_with_gt.bag"
    "${BASE}/indoor_45_13_snapdragon_with_gt.bag"
    "${BASE}/indoor_45_14_davis_with_gt.bag"
    "${BASE}/indoor_45_14_snapdragon_with_gt.bag"
    "${BASE}/indoor_45_16_davis.bag"
    "${BASE}/indoor_45_16_snapdragon.bag"

    # Outdoor forward facing
    "${BASE}/outdoor_forward_1_davis_with_gt.bag"
    "${BASE}/outdoor_forward_1_snapdragon_with_gt.bag"
    "${BASE}/outdoor_forward_2_davis.bag"
    "${BASE}/outdoor_forward_2_snapdragon.bag"
    "${BASE}/outdoor_forward_3_davis_with_gt.bag"
    "${BASE}/outdoor_forward_3_snapdragon_with_gt.bag"
    "${BASE}/outdoor_forward_5_davis_with_gt.bag"
    "${BASE}/outdoor_forward_5_snapdragon_with_gt.bag"
    "${BASE}/outdoor_forward_6_davis.bag"
    "${BASE}/outdoor_forward_6_snapdragon.bag"
    "${BASE}/outdoor_forward_9_davis.bag"
    "${BASE}/outdoor_forward_9_snapdragon.bag"
    "${BASE}/outdoor_forward_10_davis.bag"
    "${BASE}/outdoor_forward_10_snapdragon.bag"

    # Outdoor 45° downward facing
    "${BASE}/outdoor_45_1_davis_with_gt.bag"
    "${BASE}/outdoor_45_1_snapdragon_with_gt.bag"
    "${BASE}/outdoor_45_2_davis.bag"
    "${BASE}/outdoor_45_2_snapdragon.bag"
)

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
mkdir -p "${DEST_DIR}"
echo "Destination : ${DEST_DIR}"
echo "Files       : ${#BAGS[@]}"
echo "-------------------------------------------"

FAILED=()

for url in "${BAGS[@]}"; do
    filename=$(basename "${url}")
    dest_file="${DEST_DIR}/${filename}"

    if [[ -f "${dest_file}" ]]; then
        echo "[SKIP]  ${filename} (already exists)"
        continue
    fi

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

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "==========================================="
echo "Done. $(( ${#BAGS[@]} - ${#FAILED[@]} )) / ${#BAGS[@]} downloaded successfully."

if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "Failed:"
    for f in "${FAILED[@]}"; do echo "  - ${f}"; done
    exit 1
fi