# Model Context Protocol (MCP) — 1.6.0

CanarryLookup supports MCP tool discovery and invocation through local stdio child processes and MCP Streamable HTTP endpoints. Connected tools are offered to the model when Agent mode is enabled.

## Device-specific ownership

Every browser/device has a separate MCP server list and configuration. A server added from Device 2 is stored with Device 2’s identity; Device 3 cannot list, test, edit, delete or invoke it. Environment values and HTTP headers are not returned by the MCP listing API. MCP tools are invoked only from the requesting device’s MCP set.

The first browser is the owner device and owns global worldwide tunnel credentials. MCP ownership is independent: non-owner paired devices can add and manage their own MCP servers.

## Stdio

The executable, argument array and environment are configured explicitly. No shell is used to start the child. The child process runs with the CanarryLookup OS user’s permissions and an environment allowlist plus configured variables. This release launches a fresh stdio process for discovery and each call; stateful servers requiring a persistent process may not work correctly.

## Streamable HTTP

The app performs MCP initialization, sends the initialized notification, uses the negotiated protocol version/session ID when provided, and issues `tools/list` and `tools/call` requests. Configure authentication headers as needed. HTTPS is strongly recommended for non-loopback servers.

## Normal and Harness modes

MCP integrations remain available to Agent mode in both application modes. Normal mode disables the app’s built-in workspace filesystem and command tools. Harness mode enables those built-in tools for the current device only. An MCP server may independently have filesystem, shell, browser, cloud or other permissions; therefore Normal mode does not neutralize the permissions of a connected MCP server.

## Trust boundary

MCP tool calls are real actions. Never connect an untrusted server. Restrict local filesystem roots, credentials and remote service permissions. A stdio server runs on the CanarryLookup host as the same operating-system user as CanarryLookup; it does not run on the remote browser/phone. A remote device that needs to use a service running on itself must expose an authenticated MCP Streamable HTTP endpoint reachable from the host. Stdio servers are not sandboxed by the app. MCP configuration records are stored in the local SQLite database; protect the data directory and backups.
