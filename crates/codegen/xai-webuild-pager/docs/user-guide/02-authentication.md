# Authentication

WeBuild resolves credentials per model. For this fork the **default model is
`qwen3.7-max`**, which uses an OpenAI-compatible API key (DashScope / Qwen).
Optional xAI Grok models and enterprise SSO flows remain available when you
configure them.

---

## API keys (recommended default)

### Qwen / DashScope (default model)

```bash
export DASHSCOPE_API_KEY="sk-..."
# or
export QWEN_API_KEY="sk-..."
webuild
```

These env vars are wired into the baked-in `qwen3.7-max` catalog entry
(`default_models.json`). You can also pin a key in config:

```toml
# ~/.webuild/config.toml
[model."qwen3.7-max"]
api_key = "sk-..."
# or: env_key = "DASHSCOPE_API_KEY"
```

Create keys in your DashScope / Alibaba Cloud console (or whatever gateway
you point `base_url` at).

### Other OpenAI-compatible providers

```toml
[model.my-model]
model = "your-model-id"
base_url = "https://api.example.com/v1"
api_backend = "chat_completions"
env_key = "MY_API_KEY"
```

```bash
export MY_API_KEY="..."
webuild -m my-model
```

See [Custom Models](11-custom-models.md).

### Optional: xAI Grok

For baked-in `grok-build` (and other xAI catalog rows when present):

```bash
export XAI_API_KEY="xai-..."
webuild -m grok-build
```

Or obtain a session via browser login (below) when using xAI dual-route models.

---

## Browser login (optional / xAI-oriented)

Some catalog entries still support session-token auth against a chat proxy
(historical SpaceXAI flow). On first launch **without** a provider API key,
WeBuild may open a browser sign-in:

```bash
webuild
# or force re-auth:
webuild login
```

| Flag | Description |
|------|-------------|
| `--oauth` | Browser OAuth (default when using this flow) |
| `--device-auth` (alias `--device-code`) | Device-code flow for headless / remote environments |

Credentials are stored in `~/.webuild/auth.json` and refreshed in the background
when the provider supports it. Sign out with `webuild logout`.

> For day-to-day use with `qwen3.7-max`, prefer `DASHSCOPE_API_KEY` /
> `QWEN_API_KEY` — you do not need browser login.

---

## OIDC (Customer SSO)

Authenticate through your own Identity Provider (IdP) — such as Okta, Azure AD,
or Auth0 — instead of a public browser login.

### 1. Register a public client in your IdP

- Grant type: Authorization Code with PKCE
- Redirect URI: `http://127.0.0.1/callback` (loopback; port is chosen at runtime)
- No client secret (PKCE)

### 2. Configure the CLI

```toml
# ~/.webuild/config.toml
[webuild_com_config.oidc]
issuer = "https://acme.okta.com"
client_id = "0oa1b2c3d4e5f6g7h8i9"
```

Or:

```bash
export WEBUILD_OIDC_ISSUER="https://acme.okta.com"
export WEBUILD_OIDC_CLIENT_ID="0oa1b2c3d4e5f6g7h8i9"
```

Optional proxy override for org-managed inference:

```bash
export WEBUILD_CLI_CHAT_PROXY_BASE_URL="https://webuild-proxy.acme.com/v1"
```

### 3. Run `webuild`

The CLI discovers `{issuer}/.well-known/openid-configuration`, opens the IdP
login page, and stores tokens in `~/.webuild/auth.json`.

| Field | Default | Notes |
|-------|---------|-------|
| `scopes` | `["openid", "profile", "email", "offline_access", "api:access"]` | `offline_access` enables silent refresh |
| `audience` | None | Required by some IdPs (e.g. Auth0) |

---

## External Auth Provider

When browser login is not possible (sandboxed VMs, CI, air-gapped networks),
delegate authentication to an external binary or script.

### How It Works

```
+--------------+     sh -c     +------------------------+
|   WeBuild    |-------------->|  your auth binary      |
|              |               |                        |
|  reads       |<-- stdout ----|  prints token          |
|  auth.json   |               |                        |
|              |   (stderr)    |  prints status/URLs    |--> surfaced to user
+--------------+               +------------------------+
```

1. WeBuild runs your command via `sh -c "<command>"`
2. Your binary runs whatever auth flow it needs
3. **stderr** is human-readable (login URLs, status); WeBuild may surface the first `https://` URL as a clickable link in the TUI
4. **stdout** is the access token WeBuild stores
5. Exit 0 = success; non-zero falls back to other configured methods

### The stdout / stderr Contract

| Stream | What to print | Who sees it |
|--------|---------------|-------------|
| stdout | Access token only (no extra text) | WeBuild only |
| stderr | Status, errors, login URLs | User (via TUI / logs) |

Configure with `auth_provider_command` under your auth config (see
`~/.webuild/config.toml` examples in [Configuration](05-configuration.md)).

---

## Hot Reload

WeBuild picks up changes to `~/.webuild/auth.json` automatically. If you update
credentials externally, the next API call uses them without a restart.

---

## Auth Precedence

WeBuild resolves credentials for each request, highest to lowest:

1. **Per-model `api_key` or `env_key`** — `[model.<name>]` in `config.toml` (includes the default `qwen3.7-max` env keys)
2. **Active session token** — browser / OIDC / external provider in `~/.webuild/auth.json`
3. **`XAI_API_KEY`** — global fallback (mainly for xAI-oriented models)

When more than one login flow is configured, the session token is filled from
the first available source:

1. **External auth provider** (`auth_provider_command`)
2. **Enterprise OIDC** — `[webuild_com_config.oidc]` or `WEBUILD_OIDC_*`
3. **Browser OAuth** — optional legacy / proxy-oriented flow

During a session, the active method handles mid-session refreshes.

---

## Troubleshooting

### Default model returns 401

- Confirm `echo ${#DASHSCOPE_API_KEY}` (or `QWEN_API_KEY`) is non-zero in the same shell
- Confirm you did not override `[model."qwen3.7-max"]` with a wrong `api_key`
- Check `base_url` if you use a custom gateway

### Debug logging

Set `RUST_LOG` for file log / headless stderr verbosity. In headless mode (`-p`),
`RUST_LOG` defaults to `off` so only the answer is printed — set
`RUST_LOG=error` (or broader) to see logs on stderr.
