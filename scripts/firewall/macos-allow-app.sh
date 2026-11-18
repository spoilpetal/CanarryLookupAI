#!/usr/bin/env bash
# macOS Application Firewall allow rule for the Python interpreter running CanarryLookup.
# This does not create a router port-forward or expose the app to the public internet.
set -euo pipefail
PYTHON_BIN="${1:-$(command -v python3 || true)}"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Usage: sudo $0 /absolute/path/to/python3" >&2
  exit 1
fi
FW="/usr/libexec/ApplicationFirewall/socketfilterfw"
if [[ ! -x "$FW" ]]; then echo "macOS Application Firewall utility not found." >&2; exit 1; fi
"$FW" --add "$PYTHON_BIN"
"$FW" --unblockapp "$PYTHON_BIN"
"$FW" --setglobalstate on
printf 'Allowed incoming connections for: %s\n' "$PYTHON_BIN"
printf 'Review System Settings > Network > Firewall. Remove this app rule there if needed.\n'
