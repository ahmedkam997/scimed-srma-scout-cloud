#!/usr/bin/env bash
# Shared, read-only build for every production and verification runner.
set -euo pipefail
dest="${RUNNER_TEMP:?}/prospero-mcp"
git clone --quiet --depth 1 --branch v0.2.2 https://github.com/erichuang777777/PROSPERO-MCP.git "$dest"
test "$(git -C "$dest" rev-parse HEAD)" = "5ca9b96d3f77bbe997c284bd4f086e33b9b3d43e"
python scripts/patch_prospero_cli.py "$dest/src/prospero-client.ts"
npm install --prefix "$dest" --no-audit --no-fund
npm run build --prefix "$dest"
test -s "$dest/dist/cli.js"
echo "PROSPERO_CLI_JS=$dest/dist/cli.js" >> "${GITHUB_ENV:?}"
echo "PROSPERO_CACHE_ENABLED=false" >> "$GITHUB_ENV"
echo "PROSPERO_PAGINATION_CONTRACT=FIXED_LINE_V1" >> "$GITHUB_ENV"
