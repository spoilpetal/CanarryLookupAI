#!/usr/bin/env bash
set -euo pipefail
PORT="${1:-8080}"
SUBNET="${2:-192.168.0.0/24}"
if command -v firewall-cmd >/dev/null && systemctl is-active --quiet firewalld; then
  ZONE="$(sudo firewall-cmd --get-active-zones | awk 'NR==1 {print $1}')"
  ZONE="${ZONE:-public}"
  sudo firewall-cmd --zone="$ZONE" --remove-rich-rule="rule family=\"ipv4\" source address=\"$SUBNET\" port port=\"$PORT\" protocol=\"tcp\" accept" --permanent
  sudo firewall-cmd --reload
elif command -v ufw >/dev/null && sudo ufw status | grep -q 'Status: active'; then
  sudo ufw delete allow from "$SUBNET" to any port "$PORT" proto tcp
else
  echo 'No supported active firewall manager detected; no change made.' >&2; exit 1
fi
