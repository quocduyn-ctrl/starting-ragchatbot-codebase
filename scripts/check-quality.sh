#!/usr/bin/env bash
# Run all frontend code-quality checks without modifying files.
# Exits non-zero if any file is not properly formatted.
# Suitable for CI or a pre-push hook.
#
# Run from the repo root: ./scripts/check-quality.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d node_modules ]; then
    echo "Installing frontend tooling (one-time)..."
    npm install
fi

echo "==> Prettier format check (frontend/)"
npx prettier --check "frontend/**/*.{html,css,js,json,md}"

echo
echo "All quality checks passed."
