#!/usr/bin/env bash
# Remove the CanarryLookup Python application allow entry; this does not disable macOS Firewall.
set -euo pipefail
PYTHON_BIN="${1:-$(command -v python3 || true)}"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Usage: sudo $0 /absolute/path/to/python3" >&2
  exit 1
fi
FW="/usr/libexec/ApplicationFirewall/socketfilterfw"
if [[ ! -x "$FW" ]]; then echo "macOS Application Firewall utility not found." >&2; exit 1; fi
"$FW" --remove "$PYTHON_BIN"
printf 'Removed the application firewall entry for: %s\n' "$PYTHON_BIN"
printf 'The macOS Application Firewall remains enabled.\n'
