# Deployment and network sharing — 1.6.0

CanarryLookup is a personal multi-device workspace. Run one host and pair other browsers/devices to it.

## LAN

```bash
python app.py --host 0.0.0.0 --port 8080
```

Use Settings → Network access to view the LAN address. Open it on another device on the same network. Use the firewall script for your operating system; it adds a LAN-restricted rule and does not disable the firewall. For public networks, enable the global username/password protection.

## Pair devices

The first browser becomes the owner. On that browser, Settings → Device identity & privacy → Create pairing code. Enter the one-time code on the new browser when prompted. Codes expire after 10 minutes and can be used once. The owner can revoke devices from Settings. CLI commands: `python app.py --pair-code`, `python app.py --devices`, `python app.py --revoke-device DEVICE_ID`.

Each paired browser has private chats, projects, memory, uploads, generated images, provider settings, MCP servers and workspace files. A remote browser can use the host's Ollama through the host app while maintaining its own conversations. Cloud provider keys and MCP credentials configured by a device are scoped to that device.

## Public tunnel

Public tunnels require global Basic authentication with a unique password of at least 16 characters. Only the owner device can save provider tokens or control the tunnel.

- ngrok: install `ngrok`, enter its authtoken in owner Settings, then connect.
- Cloudflare Quick Tunnel: install `cloudflared`; no token/domain required, but the URL is temporary.
- Cloudflare named tunnel: create a tunnel and configure the public hostname in Cloudflare, then enter its tunnel token and hostname in owner Settings.
- Tailscale Funnel: install and sign in to Tailscale on the host, enable Funnel for the tailnet, then connect. The app does not save a Tailscale auth key.

The app never exposes Ollama's port 11434. Do not configure router port forwarding for the application. Treat the public URL and Basic credentials as private.

## Normal and Harness modes

Normal mode disables built-in workspace and command tools. Harness mode enables the existing workspace tools and allowlisted command runner for that device only. It is not a sandbox and does not provide full GUI automation. MCP integrations remain independently available in both modes and can have their own permissions.

## Backups

Stop the server and back up the complete data directory, including `studio.sqlite3`, uploads, generated images, workspace and `.canarry-device-secrets.key`. The key is required to decrypt saved per-device provider and tunnel credentials.

## LAN binding and remote devices

For access from other devices on your local network, launch:

```bash
python app.py --host 0.0.0.0 --port 8080
```

The loopback address `127.0.0.1` is accessible only from the same
computer. Binding to `0.0.0.0` makes the service listen on network
interfaces, subject to firewall and router restrictions.

Find your LAN address on Linux:

```bash
hostname -I
```

Open `http://LAN-IP:8080` from another device on the same trusted network.

Allow inbound TCP port 8080 only from your trusted LAN subnet.
Do not disable your firewall or expose the application directly to
the public internet. Use authenticated remote access for worldwide access.
