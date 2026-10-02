#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
node scripts/assets.mjs
mkdir -p dist/server dist/.openai
node_modules/.bin/esbuild worker/index.js --bundle --format=esm --platform=browser --target=es2022 --outfile=dist/server/index.js
cp .openai/hosting.json dist/.openai/hosting.json
