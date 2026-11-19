# Security model and limitations

## Application controls

- Loopback bind by default.
- Optional global HTTP Basic authentication; public tunnels require a username and a password of at least 16 characters.
- One owner browser identity, one-time pairing codes (10-minute expiry, single use), paired-device listing and revocation.
- Device-scoped chats, projects, memories, uploads, generated images, provider settings, MCP servers and workspace directories.
- Owner-device-only worldwide tunnel credential management and tunnel start/stop controls.
- Per-device Normal/Harness mode. Normal mode omits built-in filesystem and command tools; Harness mode enables the existing workspace tools and allowlisted command runner for that device.
- Cross-origin mutation checks using Origin and Fetch Metadata headers.
- Per-IP in-process request throttling, CSP, frame denial, MIME sniffing prevention, referrer and permissions policy headers.
- Workspace path containment checks; command execution uses a fixed executable allowlist, `shell=False` and a timeout.

## Credentials and data

Per-device settings values, including cloud provider API keys and ngrok/Cloudflare tunnel tokens, are encrypted using Fernet. The encryption key is stored in `.canarry-device-secrets.key` in the application data directory and is restricted to the current OS user where supported. Back up the key and database together. If the key is lost, encrypted settings cannot be recovered. MCP server configuration records (including configured stdio environment values and HTTP headers) are stored in SQLite and are not separately encrypted; protect the database and backups. The SQLite database file is chmod 0600 where supported.

The owner device’s pre-CanarryLookupAI records are migrated to the first owner identity. Other devices receive isolated data scopes. A browser’s device cookie is a bearer identity: anyone who steals the cookie can act as that device. Device revocation removes the identity record, making the cookie unusable.

## Harness and MCP limitations

Harness mode is an explicit per-device opt-in, but its tools execute on the CanarryLookup host (not the remote browser/phone computer) and it is not an OS sandbox. The existing command runner allows selected executables (including Python and Node) and those can execute code with the CanarryLookup process user’s permissions. There is no per-command approval prompt in this release. Run the app as an unprivileged OS user and do not enable Harness mode on devices you do not trust.

MCP servers remain available in both modes when Agent mode is enabled. Normal mode only disables built-in workspace/shell tools; it cannot restrict the capabilities of an MCP server. A stdio MCP process runs as the CanarryLookup OS user. Remote MCP servers receive the configured request headers and tool arguments.

## Network and tunnel limitations

- LAN sharing is password-free by default for a trusted private network. Enable global authentication before public access.
- Cloudflare Quick Tunnel is temporary; a named Cloudflare tunnel token requires a hostname already configured in Cloudflare.
- ngrok uses the configured authtoken through the `NGROK_AUTHTOKEN` environment variable for its child process.
- Tailscale Funnel requires the host's Tailscale CLI to be signed in and Funnel enabled; the app does not store a Tailscale auth key.
- Do not expose Ollama’s port 11434 or SQLite directly. Do not port-forward the app directly from the router.
- Use HTTPS for remote access. Basic authentication credentials must not traverse plain HTTP on untrusted networks.

The built-in rate limiter is process-local and is not a distributed WAF. This is a personal multi-device application, not a hardened multi-tenant SaaS. Use a reverse proxy/access gateway for additional controls where appropriate.
