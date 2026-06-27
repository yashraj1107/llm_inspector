#!/usr/bin/env bash
# docker_test.sh — Proves that llm_inspector's SQLite file persists across
# container restarts via a host-mounted volume (uses podman).
#
# Pass/fail criterion:
#   rows_after_run2 == rows_after_run1 + 1
#   (the second container appended to the SAME file the first one created)
#
# Usage: bash docker_test.sh

set -euo pipefail

IMAGE="llm_inspector_test"
VOLUME_DIR="$(pwd)/docker_test_data"
DB_PATH="${VOLUME_DIR}/traces.db"

# Helper: read row count from the host-side DB
row_count() {
    python3 -c "
import sqlite3, sys
db = '${DB_PATH}'
try:
    conn = sqlite3.connect(db)
    n = conn.execute('SELECT COUNT(*) FROM traces').fetchone()[0]
    conn.close()
    print(n)
except Exception as e:
    print(0)
"
}

echo "============================================================"
echo " llm_inspector — Docker volume persistence test"
echo "============================================================"

# ---------------------------------------------------------------------------
# Step 0: Build
# ---------------------------------------------------------------------------

echo ""
echo "[0] Building image '${IMAGE}' with podman …"
podman build -t "${IMAGE}" . --quiet
echo "    Build complete."

# ---------------------------------------------------------------------------
# Step 1: First container run  (marker = run_1)
# ---------------------------------------------------------------------------

echo ""
echo "[1] Running container #1 (marker=run_1) …"
mkdir -p "${VOLUME_DIR}"
podman run --rm \
    -v "${VOLUME_DIR}:/app/llm_inspector_data:Z" \
    "${IMAGE}" \
    python docker_test_script.py run_1

ROWS_AFTER_1=$(row_count)
echo ""
echo "    Host-side row count after run #1: ${ROWS_AFTER_1}"

# ---------------------------------------------------------------------------
# Step 2: Second container run (marker = run_2)
# ---------------------------------------------------------------------------

echo ""
echo "[2] Running container #2 (marker=run_2) with the SAME volume mount …"
podman run --rm \
    -v "${VOLUME_DIR}:/app/llm_inspector_data:Z" \
    "${IMAGE}" \
    python docker_test_script.py run_2

ROWS_AFTER_2=$(row_count)
echo ""
echo "    Host-side row count after run #2: ${ROWS_AFTER_2}"

# ---------------------------------------------------------------------------
# Step 3: Verdict
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
EXPECTED=$(( ROWS_AFTER_1 + 1 ))
if [ "${ROWS_AFTER_2}" -eq "${EXPECTED}" ]; then
    echo "  PASS ✓"
    echo "  Run #1 wrote ${ROWS_AFTER_1} row(s)."
    echo "  Run #2 appended 1 more → ${ROWS_AFTER_2} total."
    echo "  Both containers used the SAME persistent volume."
else
    echo "  FAIL ✗"
    echo "  Expected ${EXPECTED} rows after run #2, got ${ROWS_AFTER_2}."
    echo "  The second container may have started with a fresh DB."
    exit 1
fi
echo "============================================================"
