#!/usr/bin/env bash
# script/build — compile Angular into the Python package + build distributions
#
# Usage:
#   ./script/build              # full build
#   ./script/build --skip-ng    # skip Angular (use existing mastodon_is_my_blog/static/browser/)
#   ./script/build --skip-wheel # compile Angular only, do not build wheel
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATIC_DEST="${REPO_ROOT}/mastodon_is_my_blog/static/browser"

SKIP_NG=false
SKIP_WHEEL=false

for arg in "$@"; do
  case "$arg" in
    --skip-ng)    SKIP_NG=true ;;
    --skip-wheel) SKIP_WHEEL=true ;;
  esac
done

echo "==> mastodon_is_my_blog build"
echo "    repo root: ${REPO_ROOT}"
echo ""

# Step 1: Compile Angular
if [ "$SKIP_NG" = false ]; then
  echo "==> Step 1: Building Angular frontend (production)..."
  cd "${REPO_ROOT}/web"
  pwd
  npm ci # --prefer-offline
  npx ng build --configuration production
  cd "${REPO_ROOT}"
  echo "    Angular build complete."
else
  echo "==> Step 1: Skipping Angular build (--skip-ng)"
fi

# Step 2: Verify compiled assets landed in the Python package
echo ""
echo "==> Step 2: Verifying Angular output in mastodon_is_my_blog/static/browser/ ..."
if [ ! -d "${STATIC_DEST}" ]; then
  echo "ERROR: Angular output not found: ${STATIC_DEST}"
  echo "       Run without --skip-ng, or: cd web && ng build --configuration production"
  exit 1
fi

FILE_COUNT=$(find "${STATIC_DEST}" -type f | wc -l | tr -d ' ')
echo "    Found ${FILE_COUNT} files in ${STATIC_DEST}"

# Step 3: Build the Python wheel
if [ "$SKIP_WHEEL" = false ]; then
  echo ""
  echo "==> Step 3: Building Python wheel..."
  cd "${REPO_ROOT}"
  uv run python -m build --sdist --wheel --no-isolation
  echo ""
  echo "    Distribution files in dist/:"
  ls -lh "${REPO_ROOT}/dist/"* 2>/dev/null || true
else
  echo ""
  echo "==> Step 3: Skipping wheel build (--skip-wheel)"
fi

echo ""
echo "==> Build complete."
