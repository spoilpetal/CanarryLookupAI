# Provider adapters and remote access — 1.6.0

## AI providers

AI provider settings are scoped to each paired device. Device 1 can use host-local Ollama while Device 2 can independently configure a cloud API key; each device retains its own chats and provider settings. A device has one active provider configuration at a time, but different devices can use different providers simultaneously. When a remote device selects the default `http://127.0.0.1:11434` Ollama endpoint, the request is made by the CanarryLookup host process, so this reaches Ollama on the host, not on the phone/browser.

- Ollama: native `/api/tags`, `/api/show` and streamed `/api/chat`.
- OpenAI-compatible: `/models` and streamed `/chat/completions`, including function tools.
- Anthropic: native Messages API with SSE and tool-use blocks.
- Google Gemini: native GenerateContent streaming, function calling, image input and supported image output.

Provider API keys are stored in encrypted per-device settings. The encryption key is `.canarry-device-secrets.key`; back it up with the database.

## Tunnel providers

Only the owner device can configure worldwide tunnel credentials or start/stop the host tunnel. Secrets are encrypted in per-device settings and never returned to other devices.

| Provider | Credential | Notes |
|---|---|---|
| ngrok | ngrok authtoken | Install `ngrok`; save the authtoken in owner Settings. The child process receives it through `NGROK_AUTHTOKEN`. |
| Cloudflare | Named Tunnel token + hostname, or no token for Quick Tunnel | Install `cloudflared`. For named tunnels, create/configure the tunnel and public hostname in Cloudflare first, then save the token and hostname. Quick Tunnel is temporary and does not require a token. |
| Tailscale Funnel | Existing host CLI login | Install and sign in to Tailscale on the host; enable Funnel for the tailnet. The app does not store a Tailscale auth key. |

CLI alternatives:

```bash
# Create a one-time device pairing code from the host terminal
python app.py --pair-code

# Start ngrok using a token supplied at launch (avoid shell history; Settings is preferred)
CANARRY_NGROK_AUTHTOKEN='YOUR_TOKEN' python app.py --host 127.0.0.1 --port 8080 --tunnel ngrok

# Start a named Cloudflare tunnel (hostname must already be routed to this tunnel)
CANARRY_CLOUDFLARE_TUNNEL_TOKEN='YOUR_TOKEN' CANARRY_CLOUDFLARE_HOSTNAME='ai.example.com' python app.py --host 127.0.0.1 --port 8080 --tunnel cloudflare

# Tailscale requires a signed-in CLI session
python app.py --host 127.0.0.1 --port 8080 --tunnel tailscale
```

Do not paste tokens into shared terminal recordings or logs. CLI environment variables are process environment values and may be visible to privileged local users. Owner Settings is preferred for persistent encrypted storage.
