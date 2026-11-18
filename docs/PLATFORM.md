# Cross-platform behavior — 1.6.0

CanarryLookup AI 1.6.0 targets Python 3.11+ on Windows, macOS and Linux. The application uses each OS user’s standard application-data location rather than storing live data in the source folder.

## Persistent storage

| Operating system | Default location |
|---|---|
| Windows | `%APPDATA%\CanarryLookupAI` |
| macOS | `~/Library/Application Support/CanarryLookupAI` |
| Linux | `$XDG_DATA_HOME/CanarryLookupAI`, falling back to `~/.local/share/CanarryLookupAI` |

The data directory contains `studio.sqlite3`, `uploads/`, `generated/`, `workspace/`, `device-workspaces/` and `.canarry-device-secrets.key`. Keep the encryption key with the database in a secure backup. `CANARRY_DATA` overrides the data directory; `CANARRY_WORKSPACE` overrides the workspace root.

## Device separation and migration

Open CanarryLookup in a browser on the host computer first; that browser becomes the owner device. Existing 1.5.0 records are assigned to it on first request after upgrade. Other browsers must be paired using a one-time code from Settings → Device identity & privacy. Chats, projects, memories, uploads, generated images, provider settings, MCP servers and workspace roots are scoped to each device. Non-owner workspace files live in `device-workspaces/<device-id>/`, outside the owner workspace tree so the owner agent cannot browse them by traversing the owner workspace.

The owner can create a pairing code in the UI. The code is valid for 10 minutes and one use. Device revocation is available in Settings or through `python app.py --devices` and `python app.py --revoke-device DEVICE_ID`.

## Firewall scripts

- Windows PowerShell: `scripts/firewall/windows-allow-lan.ps1` (run elevated); undo with `windows-remove.ps1`.
- macOS: `sudo scripts/firewall/macos-allow-app.sh /absolute/path/to/python3`. This enables the Application Firewall and adds/unblocks the Python executable. Review the app permission in System Settings → Network → Firewall. Remove the app entry with `sudo scripts/firewall/macos-remove-app.sh /absolute/path/to/python3`; the firewall remains enabled.
- Linux: `sudo scripts/firewall/linux-allow-lan.sh 8080 192.168.0.0/24`. The script supports one active firewall manager (firewalld or UFW), restricts access to the supplied LAN subnet and refuses when both are active. Use `linux-remove-lan.sh` to undo.

The Linux script does not alter nftables-only configurations. For those systems, add a rule using the existing firewall manager’s persistent configuration rather than flushing or replacing the ruleset. Never disable your firewall just to make CanarryLookup reachable.

## Platform-specific notes

### Windows

Use PowerShell as Administrator for the firewall scripts. The Windows rule applies only to the Private profile and LocalSubnet. Python must be allowed by Windows Defender Firewall for incoming connections.

### macOS

macOS Application Firewall is application-oriented rather than a simple port-rule interface. The provided script adds the Python interpreter running CanarryLookup and enables the firewall; macOS may display an authorization prompt. If multiple Python installations are used, pass the exact interpreter from the active virtual environment (`.venv/bin/python`).

### Linux / Arch Linux

Use either firewalld or UFW, not both. The provided Linux script detects the active manager. For firewalld it adds a rich rule to the active zone from the specified subnet; for UFW it adds a source-restricted TCP rule. Adjust the subnet to match your router, e.g. `192.168.0.0/24` only when that is your LAN range.

## Harness mode

Normal mode disables built-in workspace and command tools. Harness mode enables the existing workspace file tools and allowlisted command runner for that browser/device only. It is not an OS sandbox or full desktop GUI automation system. Commands execute as the account running CanarryLookup. Run as an unprivileged user and only enable Harness mode on trusted devices.

## Provider and MCP portability

Ollama, MCP stdio executables and tunnel CLIs must be installed on the host running CanarryLookup. Device-specific MCP stdio processes execute on that host under its OS account, but their configurations and tool availability are isolated by device identity. A remote device that needs access to a service running on itself must expose a Streamable HTTP MCP endpoint reachable from the host; browser code cannot launch a local stdio process on the remote device. Cloud API keys and settings are device-scoped. Tailscale requires the host CLI to be signed in; ngrok and Cloudflare credentials can be stored from the owner device Settings.

The release is syntax-checked and tested with isolated API fixtures. Windows/macOS firewall behavior, provider accounts, actual external tunnels and real MCP services must still be validated on the target OS and with the user's credentials.

## Starting the server for LAN access

Linux and macOS:

```bash
python app.py --host 0.0.0.0 --port 8080
```

Windows PowerShell:

```powershell
python app.py --host 0.0.0.0 --port 8080
```

`127.0.0.1` is loopback-only. `0.0.0.0` listens on network interfaces.
This does not automatically configure the firewall.

Find your host address:

- Linux: `hostname -I`
- macOS: `ipconfig getifaddr en0` (Wi-Fi; interface may differ)
- Windows: `ipconfig`

Visit `http://HOST-LAN-IP:8080` from another device.
Both devices must be on a network that permits local communication.

Use a firewall rule restricted to your trusted LAN subnet.
Public internet access requires authenticated remote access.
