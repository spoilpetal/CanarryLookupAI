# CanarryLookup AI 1.6.0

A local-first AI workspace with Ollama, OpenAI-compatible APIs, native Anthropic and Google Gemini adapters, workspace tools, long-term memory, projects, file attachments, pinned chats, and Model Context Protocol (MCP) tool servers.

Repository: <https://github.com/spoilpetal/CanarryLookupAI>

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Install on Windows, macOS and Linux](#install-on-windows-macos-and-linux)
- [Run and update](#run-and-update)
- [Connect an AI provider](#connect-an-ai-provider)
- [MCP servers](#mcp-servers)
- [Data and backups](#data-and-backups)
- [Share CanarryLookup on your network](#share-canarrylookup-on-your-network)
- [Device pairing and private workspaces](#device-pairing-and-private-workspaces)
- [Normal and Harness modes](#normal-and-harness-modes)
- [Firewall setup](#firewall-setup)
- [Security notes](#security-notes)
- [Cross-platform details](docs/PLATFORM.md)
- [1.6.0 build report](BUILD-REPORT.md)
- [Troubleshooting](#troubleshooting)
- [Validation status](#validation-status)

## Features

- Local Ollama chat and OpenAI-compatible API providers.
- Native Anthropic Messages API adapter, including streaming and tool use.
- Native Google Gemini `streamGenerateContent` adapter, including streaming, image input and function calling.
- Gemini image generation for models that expose image output; OpenAI-compatible image-generation endpoints are also supported.
- Agent mode with workspace tools and connected MCP tools.
- MCP stdio and Streamable HTTP transports.
- Persistent conversations, rename/delete, pin/unpin, individual Markdown export and one-click ZIP export of all chats, projects and local SQLite storage.
- File attachments, text extraction for common formats, PDF and DOCX extraction, and vision image input.
- Long-term user-managed memory, system instructions, temperature and response-token settings.
- Theme selection, compact messages, Enter-to-send, automatic scroll and default Agent mode preferences.
- Responsive layouts for compact windows, tablets, phones and short displays; collapsible sidebars, animated welcome state, reduced-motion support and matching browser-tab / welcome-page branding.
- Easy network sharing: automatic LAN address discovery, optional global username/password protection, and managed Cloudflare, ngrok and Tailscale Funnel connections.
- First-device owner identity, one-time device pairing codes, device revocation and owner-only worldwide tunnel credential controls.
- Device-isolated chats, projects, memories, uploads, generated images, provider settings, MCP servers and workspace directories.
- Per-device Normal mode and opt-in Harness mode. Normal mode disables built-in filesystem/shell tools; Harness mode exposes the existing workspace tools and allowlisted command runner only on that device.
- Encrypted per-device settings values using a local key file; the key must be backed up with the data directory.

## Requirements

- Python 3.11 or newer (Python 3.12 recommended).
- Linux, macOS or Windows with a supported Python build.
- Ollama for local inference, or an API key for a hosted provider.
- `uvicorn` is installed through `requirements.txt`.

## Install on Windows, macOS and Linux

### 1. Get the source

```bash
git clone https://github.com/spoilpetal/CanarryLookupAI.git
cd CanarryLookupAI
```

For a release ZIP, extract it and open a terminal in the extracted `CanarryLookupAI` folder instead.

### 2. Create an environment and install dependencies

**Windows (PowerShell)**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Linux**

Install Python 3.11+ and venv/pip support using your distribution's package manager, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Start CanarryLookup

With the virtual environment activated:

```bash
python app.py
```

Open <http://127.0.0.1:8080>. The server listens on loopback by default. Ollama is optional; connect a hosted provider in Settings if you do not use a local model.

## Run and update

Start from the project directory with the virtual environment active:

```bash
source .venv/bin/activate
python app.py
```

To update a Git clone:

```bash
git pull --ff-only
source .venv/bin/activate
pip install -r requirements.txt
```

Back up the data directory before replacing source files or changing versions. The app's database is not stored inside the source tree by default.

## Connect an AI provider

Open **Settings → AI provider**. Select a provider, enter the API base endpoint if needed, enter the API key, then use **Test connection** and **Save preferences**.

| Provider | Adapter | Default endpoint | Notes |
|---|---|---|---|
| Ollama | Native Ollama API | `http://127.0.0.1:11434` | Local inference; install and start Ollama separately. |
| OpenAI and compatible services | OpenAI-compatible Chat Completions | Provider-specific `/v1` endpoint | Supports the compatibility protocol; feature support varies by provider/model. |
| Anthropic Claude | Native Messages API | `https://api.anthropic.com/v1` | Uses `x-api-key`, `anthropic-version`, Messages streaming and native tool-use blocks. |
| Google Gemini | Native Gemini API | `https://generativelanguage.googleapis.com/v1beta` | Uses the Gemini API key through the `x-goog-api-key` header and native `streamGenerateContent` / function-call format. |

### Ollama

Install Ollama using its official instructions, start the service, and pull a model. For example:

```bash
ollama serve
# In another terminal:
ollama pull qwen2.5-coder:3b
```

Select **Ollama (local)** and use the model selector in the chat composer.

### Anthropic

Create an API key in the Anthropic Console. Select **Anthropic Claude API**, keep the default endpoint, enter the key and test the connection. Use a model ID available to your Anthropic account. Anthropic's Messages API does not provide image generation; image generation remains unavailable through this adapter.

### Google Gemini

Create an API key in Google AI Studio. Select **Google Gemini API**, keep the default endpoint, enter the key and test the connection. The model list is filtered to models that report `generateContent` support. For image generation, select a Gemini image-generation model in the Image generation model field (the initial suggestion is `gemini-2.5-flash-image`; availability can vary by account/region).

### OpenAI-compatible providers

Choose **OpenAI-compatible API**, select a preset or Custom endpoint, and enter the provider's base URL ending in `/v1` where required. Not every provider implements every optional OpenAI feature. Tool calls, vision, token limits and image generation depend on the provider and selected model.

## MCP servers

CanarryLookup can connect MCP tool servers from **Settings → MCP tool servers**. Connected tools are offered to the model only while Agent mode is enabled. Every MCP server and its configured credentials belong to the browser/device identity that created it. Other paired devices cannot list, edit, test or invoke that device’s MCP servers.

### Local stdio example

The form accepts an executable, a JSON argument array and an optional JSON environment object. Example configuration for a server installed with `uvx`:

- Name: `Filesystem tools`
- Transport: `Local process (stdio)`
- Executable: `uvx`
- Arguments: ` ["mcp-server-filesystem", "/absolute/path/to/allowed/folder"] `
- Environment: `{}`

The executable must already be installed and available on the CanarryLookup host's `PATH`. A stdio MCP process runs on the host, not on the remote browser/phone. For a remote device's own service, expose an authenticated Streamable HTTP MCP endpoint that the host can reach. Use absolute paths where practical. The MCP server process is launched by CanarryLookup for discovery/tool calls; this version does not keep a persistent stdio session between individual calls, so servers that rely on long-lived in-memory state may not behave as expected.

### Streamable HTTP example

Choose **Streamable HTTP** and enter the MCP endpoint URL, for example `http://127.0.0.1:8000/mcp`. Optional headers can be supplied as a JSON object, for example:

```json
{"Authorization": "Bearer YOUR_MCP_TOKEN"}
```

The older standalone MCP SSE transport is not configured as a separate option. Use Streamable HTTP for network MCP servers.

### MCP safety

MCP tools can perform real actions. A stdio server runs as the same operating-system user as CanarryLookup and can inherit filesystem permissions; a remote MCP server receives the configured headers and tool arguments. Only connect servers you trust, limit their filesystem/service permissions, and do not expose a remote MCP endpoint without its own authentication and HTTPS. MCP environment variables and HTTP headers are stored in the local SQLite database; protect the data directory and backups. MCP server configurations are device-scoped, but the app does not sandbox the MCP process: a local stdio server runs with the host OS account permissions.

## Data and backups

CanarryLookup stores its database, uploads, generated images and default workspace in a persistent per-user application-data directory, separate from the source folder. This survives application updates and normal reboots.

| Platform | Default data directory |
|---|---|
| Windows | `%APPDATA%\\CanarryLookupAI\\` |
| macOS | `~/Library/Application Support/CanarryLookupAI/` |
| Linux | `$XDG_DATA_HOME/CanarryLookupAI/`, or `~/.local/share/CanarryLookupAI/` when `XDG_DATA_HOME` is not set |

The directory contains `studio.sqlite3`, `uploads/`, `generated/`, `workspace/`, `device-workspaces/`, and `.canarry-device-secrets.key`. The encryption key is required to decrypt device-scoped provider and tunnel settings; back it up securely together with the database. Losing the key makes encrypted settings unrecoverable (chats and other non-secret data remain in SQLite). The database filename is retained for compatibility with earlier releases.

Set `CANARRY_DATA` to use a different data directory. Set `CANARRY_WORKSPACE` only when you intentionally want a separate workspace location. The legacy `OLLAMA_STUDIO_DATA` and `OLLAMA_STUDIO_WORKSPACE` environment variables remain accepted for backwards compatibility.


### Backups

Stop CanarryLookup before making a manual backup. Copy the complete platform-specific data directory shown above, including its database and subdirectories. Restoring means placing that directory back in the same location (or setting `CANARRY_DATA` to its restored location).



## Share CanarryLookup on your network

CanarryLookup can run on one computer while other devices use it through a browser. Ollama stays on the host computer at `127.0.0.1:11434`; do not expose Ollama's port.

### Local network (LAN)

1. Start CanarryLookup with the LAN bind address:

```bash
source .venv/bin/activate
python app.py --host 0.0.0.0 --port 8080
```

2. Open **Settings → Network access**. The Local network panel discovers and displays the clickable `http://LAN-IP:8080` address.
3. Open that address from another device on the same Wi-Fi/router.

LAN access is password-free by default to make first-time setup easy. This is suitable only for a trusted private network. In Settings → Network access, enable **Require username and password**, choose a username and a unique password to protect access. The app uses HTTP Basic authentication for the UI and API.

### Set a custom username and password from the CLI

```bash
python app.py --host 0.0.0.0 --port 8080 \
  --username 'my-canarry-user' \
  --password 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD'
```

Use at least 16 characters for a password when using a public tunnel. The CLI values can also be configured with `CANARRY_ACCESS_USERNAME` and `CANARRY_ACCESS_PASSWORD`. For repeatable service deployments, use a protected environment file rather than putting secrets in shell history or a systemd unit.

### Worldwide access (public tunnel)

Open **Settings → Network access → Worldwide access**, choose a provider, and click **Establish connection**. CanarryLookup displays the public URL once the provider creates it. Click **Disconnect** to stop the tunnel.

Before starting a public connection, enable sign-in protection and set a unique password of at least 16 characters. Public tunnels are rejected by the application if authentication is disabled or the password is too short.

Supported provider CLIs:

| Provider | CLI | Setup notes |
|---|---|---|
| Cloudflare Quick Tunnel | `cloudflared` | No domain required; creates a temporary `trycloudflare.com` URL. Install `cloudflared` first. |
| ngrok | `ngrok` | Install the CLI and configure your ngrok authtoken before connecting. |
| Tailscale Funnel | `tailscale` | Install and sign in to Tailscale; Funnel must be available/enabled for your tailnet. |

The same tunnel can also be started from the command line:

```bash
# Cloudflare example
python app.py --host 127.0.0.1 --port 8080 \
  --username 'my-canarry-user' \
  --password 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD' \
  --tunnel cloudflare
```

CLI tunnel mode requires the provider CLI to be installed and authenticated where applicable. The URL is printed by the provider process; the Settings screen shows its discovered URL when supported by that provider's CLI output.

A tunnel makes the app reachable from the public internet. Anyone who can reach the URL and authenticate can access your workspace, including conversations, uploads, projects and Agent/MCP capabilities. Share the URL and credentials carefully. This is a personal-workspace application, not a hardened multi-tenant service. Do not port-forward the app or Ollama ports directly from your router.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CANARRY_HOST` | `127.0.0.1` | Bind address. |
| `CANARRY_PORT` | `8080` | HTTP listen port. |
| `CANARRY_ACCESS_USERNAME` | `canarry` | HTTP Basic username when authentication is enabled. |
| `CANARRY_ACCESS_PASSWORD` | empty | Enables authentication by default when supplied. |
| `CANARRY_TUNNEL_PROVIDER` | empty | Optional startup tunnel: `cloudflare`, `ngrok` or `tailscale`. |
| `CANARRY_NGROK_AUTHTOKEN` | empty | ngrok authtoken for CLI-started tunnels; owner Settings is preferred for encrypted persistent storage. |
| `CANARRY_CLOUDFLARE_TUNNEL_TOKEN` | empty | Cloudflare remotely-managed tunnel token for CLI-started tunnels. |
| `CANARRY_CLOUDFLARE_HOSTNAME` | empty | Public hostname already routed to the named Cloudflare tunnel. |
| `CANARRY_DATA` | Platform-specific user data directory | SQLite, uploads, generated images and default workspace. |
| `CANARRY_WORKSPACE` | `<CANARRY_DATA>/workspace` | Agent workspace root. |
| `MAX_TOOL_ROUNDS` | `6` | Maximum agent tool-call rounds per response. |
| `COMMAND_TIMEOUT` | `45` | Maximum seconds for allowlisted workspace commands. |

The Settings screen can configure global authentication and owner-only tunnel credentials. Per-device settings and MCP configuration are encrypted with `.canarry-device-secrets.key`; global network authentication settings are encrypted too. Protect the data directory and back up the key with the database.

## Device pairing and private workspaces

The first browser that opens the upgraded 1.6.0 data directory becomes the owner device. Open CanarryLookup in a browser on the host computer first so the host browser becomes the owner. The owner controls global network authentication, tunnel credentials and device pairing. A different browser/device is initially unpaired and cannot access workspace APIs until it receives a one-time code.

1. On the owner device, open **Settings → Device identity & privacy → Create pairing code**.
2. On the new device, open the CanarryLookup LAN or remote URL and enter the code when prompted.
3. Give the device a recognizable name. The code expires after 10 minutes and works once.
4. The owner can review paired devices and revoke a device from the same section. CLI alternatives are `python app.py --devices` and `python app.py --revoke-device DEVICE_ID`.

Chats, projects, memories, uploads, generated images, provider credentials, MCP servers and agent workspace files are scoped to the device identity. The owner device retains the pre-1.6.0 data. Each paired device gets a separate workspace directory under `device-workspaces/DEVICE_ID/`. Provider settings are separate per device; therefore a remote phone can use the host's local Ollama endpoint (the CanarryLookup server makes the provider request from the host) while keeping that phone's chats separate. A device can also configure its own cloud AI provider. Each device has one active provider configuration at a time; switch providers in Settings when needed. Different devices can use different providers simultaneously.

The browser identity is stored in an HttpOnly, SameSite cookie. Do not copy browser profile data or the cookie to another person. Device revocation invalidates the stored identity; the next request from that browser will require pairing again. This is a personal multi-device workspace, not a hardened multi-tenant SaaS identity system.

## Normal and Harness modes

Each device has its own mode in **Settings → Device identity & privacy**.

- **Normal mode (default):** built-in filesystem and command tools are not offered to the model. MCP servers configured on that device remain available when Agent mode is enabled.
- **Harness mode:** enables the existing workspace file tools and allowlisted command runner for that device. The command runner uses `shell=False`, a fixed executable allowlist and a timeout, but it is not an OS sandbox. In particular, Python/Node tooling can execute code with the CanarryLookup process user's permissions. Enable only on a trusted host/device and run CanarryLookup as an unprivileged OS account.

Harness mode runs on the CanarryLookup host; it does not control the remote phone/browser computer and does not provide full desktop GUI automation or unrestricted remote-control features. MCP servers are independent of the Harness toggle; an MCP server can have its own external/system permissions even while the app is in Normal mode. Only connect trusted MCP servers and restrict their permissions.

## Firewall setup

Scripts are provided in `scripts/firewall/`:

- Windows: open PowerShell as Administrator and run `scripts\firewall\windows-allow-lan.ps1`. Remove with `windows-remove.ps1`.
- macOS: run `sudo scripts/firewall/macos-allow-app.sh /absolute/path/to/python3`. This enables the macOS Application Firewall and allows the Python executable; review the resulting app rule in System Settings → Network → Firewall. Remove the app entry with `sudo scripts/firewall/macos-remove-app.sh /absolute/path/to/python3` (the firewall remains enabled).
- Linux: run `sudo scripts/firewall/linux-allow-lan.sh 8080 192.168.0.0/24`. Change the subnet to match your LAN. It supports an active firewalld or UFW manager and refuses to proceed when both are active. Remove with `linux-remove-lan.sh` and the same arguments.

The scripts do not disable the firewall, open the port to the entire internet, or configure router port forwarding. Linux nftables-only setups are not modified automatically because replacing or guessing an existing ruleset is unsafe; follow the instructions in `docs/PLATFORM.md` for that case. Firewall rules only allow LAN access; a public tunnel is a separate connection.

### Export conversations

Use the down-arrow action beside an individual conversation to export it as Markdown. To export all conversations, use the **⇩** button beside the Conversations heading or **Settings → Chat exports → Export all conversations**. The browser downloads a ZIP containing one Markdown file per chat.

## Security notes

- LAN sharing is password-free by default. Enable HTTP Basic authentication before enabling a public tunnel; public tunnels require a username and a password of at least 16 characters. Never expose the app directly to the internet without authentication.
- Cross-origin browser mutations are rejected when the Origin/Fetch Metadata headers indicate a foreign origin.
- Basic per-IP request throttling and security headers are applied in the application middleware.
- Workspace path traversal is blocked; workspace command execution is restricted to a fixed executable allowlist and uses no shell.
- Per-device settings values (including provider API keys and tunnel tokens) are encrypted with a Fernet key in `.canarry-device-secrets.key`; keep that key private and back it up securely. MCP server configurations are also encrypted at rest in the SQLite database. Protect the data directory and backups regardless.
- The rate limiter is process-local and not a replacement for a reverse-proxy/WAF limit. It does not coordinate across multiple worker processes.
- Device identities separate private data and MCP connections on this single-host personal deployment. This is not a hardened multi-tenant SaaS; anyone who obtains a paired device cookie can act as that device. Owner pairing codes and browser profiles must be protected.
- Use HTTPS for remote access, firewall the raw port, run under an unprivileged account, keep dependencies updated and do not connect untrusted MCP servers.

See [`docs/SECURITY.md`](docs/SECURITY.md) and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Troubleshooting

**Provider unavailable** — Check that Ollama is running or that the endpoint/API key is correct. For Ollama, `ollama list` and `curl http://127.0.0.1:11434/api/tags` are useful checks.

**No models listed** — Verify the selected provider's model access. Anthropic/Gemini model availability depends on account access and API support.

**MCP connection fails** — Test the executable from the same user account that runs CanarryLookup, check JSON argument syntax, ensure the server speaks MCP stdio or Streamable HTTP, and inspect the configured endpoint/auth headers.

**Gemini image generation returns no image** — Choose an image-generation-capable Gemini model; ordinary text models may not return inline image data.

**LAN address not shown** — Ensure the host is connected to the same LAN/Wi-Fi, then use Refresh addresses in Settings → Network access. Check firewall access to the selected app port.

**Public tunnel fails** — Install the selected provider CLI, complete its account/device setup, enable authentication with a 16+ character password, then try again. Review the provider CLI output in the host terminal.

## Validation status

The source package is statically validated. Local API/database paths, legacy SQLite migration, pinned chats, remote authentication, endpoint protections, MCP stdio/Streamable HTTP protocol flows, Anthropic/Gemini streaming and function-call loops, and Gemini image-file persistence were exercised with local or mocked protocol fixtures. No real cloud credentials or third-party production MCP server were available, so live inference, provider billing/account entitlements, image-generation account access, and remote HTTPS deployment remain operator-side validation. Browser automation could not be completed in the build environment because its Chromium policy blocked navigation to the local test server. Do not treat mocked protocol tests or a successful model-list request as proof that every provider/model feature is supported.

### Optional systemd service

Create a dedicated account and point the service at the checked-out project. Store secrets in a root-readable environment file (`chmod 600`), not in the unit file:

```ini
# /etc/systemd/system/canarrylookup.service
[Unit]
Description=CanarryLookup AI
After=network.target

[Service]
Type=simple
User=canarrylookup
Group=canarrylookup
WorkingDirectory=/opt/CanarryLookupAI
Environment=CANARRY_HOST=127.0.0.1
Environment=CANARRY_PORT=8080
EnvironmentFile=/etc/canarrylookup.env
ExecStart=/opt/CanarryLookupAI/.venv/bin/python /opt/CanarryLookupAI/app.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/canarrylookup /opt/CanarryLookupAI/workspace

[Install]
WantedBy=multi-user.target
```

Create `/etc/canarrylookup.env` with `CANARRY_ACCESS_PASSWORD=...` and configure `CANARRY_DATA=/var/lib/canarrylookup` plus `CANARRY_WORKSPACE=/opt/CanarryLookupAI/workspace`. Ensure the service account owns the writable paths. Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now canarrylookup
sudo systemctl status canarrylookup
```

Adjust systemd sandboxing for your selected workspace and MCP server executables; some MCP servers need additional filesystem or network access.

## Agent execution boundary

Agent mode is not a security sandbox. The workspace tools constrain file paths to the workspace, but the allowlisted `python`, `node`, `npm`, `git` and related commands can execute code with the CanarryLookup operating-system account's permissions. MCP tools can have similarly broad permissions. Only expose Agent mode to trusted users and run the service under a dedicated low-privilege account.

## Network access and mobile devices

To access CanarryLookup from your phone or another computer on your
local network, start the server with:

```bash
python app.py --host 0.0.0.0 --port 8080
```

Find your computer's LAN address:

```bash
hostname -I
```

Open `http://YOUR-LAN-IP:8080` on your other device.

Important:
- `127.0.0.1` allows access only from the host computer.
- `0.0.0.0` listens on available network interfaces.
- Configure your firewall to allow TCP port 8080 from your trusted LAN.
- Your devices must be on a network that permits device-to-device communication.
- Do not expose an unauthenticated service directly to the internet.
