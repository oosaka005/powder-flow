#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

export DISPLAY="${DISPLAY:-:0}"

echo "Starting Powder Flow..."
echo

if ./run_app.sh; then
  echo
  echo "Powder Flow exited normally."
else
  status=$?
  echo
  echo "Powder Flow failed with exit code ${status}."
fi

echo
read -r -p "Press Enter to close this window..." _
