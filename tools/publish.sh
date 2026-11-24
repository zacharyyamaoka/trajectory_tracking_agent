#!/usr/bin/env bash
# Make the repo public and serve site/ on GitHub Pages (https://zacharyyamaoka.github.io/trajectory_tracking_agent/).
# Safe to run twice. Undo: gh repo edit zacharyyamaoka/trajectory_tracking_agent --visibility private --accept-visibility-change-consequences
set -euo pipefail
REPO=zacharyyamaoka/trajectory_tracking_agent
gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences
gh api -X POST "repos/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api -X PUT "repos/$REPO/pages" -f build_type=workflow >/dev/null
gh workflow run pages.yml --repo "$REPO"
echo "Publishing: https://github.com/$REPO/actions/workflows/pages.yml -> https://zacharyyamaoka.github.io/trajectory_tracking_agent/"
