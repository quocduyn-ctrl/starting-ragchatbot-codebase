#!/usr/bin/env bash
# Format all frontend files in-place using Prettier.
# Run from the repo root: ./scripts/format-frontend.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d node_modules ]; then
    echo "Installing frontend tooling (one-time)..."
    npm install
fi

echo "Formatting frontend/ ..."
npx prettier --write "frontend/**/*.{html,css,js,json,md}"
echo "Done."
