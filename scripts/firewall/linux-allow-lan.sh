#!/usr/bin/env bash
# Safely allow CanarryLookup from the private LAN only. Does not enable/disable firewalls.
set -euo pipefail
PORT="${1:-8080}"
SUBNET="${2:-192.168.0.0/24}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then echo 'Invalid TCP port.' >&2; exit 2; fi
if ! command -v sudo >/dev/null; then echo 'sudo is required.' >&2; exit 2; fi
if command -v firewall-cmd >/dev/null && systemctl is-active --quiet firewalld; then
  if command -v ufw >/dev/null && systemctl is-active --quiet ufw; then echo 'Both firewalld and UFW are active. Stop and choose one firewall manager first.' >&2; exit 3; fi
  ZONE="$(sudo firewall-cmd --get-active-zones | awk 'NR==1 {print $1}')"
  ZONE="${ZONE:-public}"
  sudo firewall-cmd --zone="$ZONE" --add-rich-rule="rule family=\"ipv4\" source address=\"$SUBNET\" port port=\"$PORT\" protocol=\"tcp\" accept" --permanent
  sudo firewall-cmd --reload
  echo "Allowed TCP $PORT from $SUBNET in firewalld zone $ZONE."
elif command -v ufw >/dev/null && sudo ufw status | grep -q 'Status: active'; then
  if systemctl is-active --quiet firewalld; then echo 'Both firewalld and UFW are active. Stop and choose one firewall manager first.' >&2; exit 3; fi
  sudo ufw allow from "$SUBNET" to any port "$PORT" proto tcp comment 'CanarryLookup AI LAN'
  echo "Allowed TCP $PORT from $SUBNET in UFW."
else
  echo 'No active supported firewalld/UFW manager detected.' >&2
  echo 'No nftables rule was changed automatically because the active ruleset cannot be safely inferred.' >&2
  echo 'Add a TCP accept rule restricted to your private LAN subnet in your existing firewall configuration.' >&2
  exit 4
fi
