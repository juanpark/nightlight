#!/usr/bin/env bash
# Scan everything that can reach GitHub: staged changes and the full git history. Non-zero exit = do not commit/push.
set -euo pipefail
cd "$(dirname "$0")/.."
gitleaks protect --staged --no-banner
gitleaks git --no-banner .
echo "secret scan: clean"
