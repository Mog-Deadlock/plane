# Mog-Deadlock fork of Plane

This branch (`mog-oidc`, forked off upstream `v0.27.0`) adds a single
piece on top of stock Plane Community Edition: a **MOG OIDC auth
provider** that authenticates Plane users against the OpenIddict
server in [`mog-platform`](https://github.com/Mog-Deadlock/mog-platform),
which itself is the OIDC bridge for Steam-canonical MOG identity.

Everything else is upstream Plane, untouched. We track upstream
forward via the standard fork merge flow.

## Why this fork exists

Plane CE's auth options are email/password + Google/GitHub/GitLab
OAuth. There is no generic OIDC adapter in CE today. We need to
authenticate Plane users with the same Steam-canonical identity the
website uses, so people don't carry around an extra Plane password.

The clean fix is a small adapter alongside `github.py` / `google.py`
in `plane/authentication/provider/oauth/` that points at our
OpenIddict endpoints. ~150 lines of Python, straight OAuth2 +
userinfo (OpenIddict speaks both protocols correctly).

## What's added

| File | Purpose |
|---|---|
| `apiserver/plane/authentication/provider/oauth/mog.py` | The MogOAuthProvider — auth/token/userinfo URLs are config-driven; default to mogdl.com's `/connect/*` endpoints |
| `apiserver/plane/authentication/views/app/mog.py` | `MogOauthInitiateEndpoint` + `MogCallbackEndpoint` (mirror of the github views) |
| `apiserver/plane/authentication/views/__init__.py` | Re-export the two new endpoints |
| `apiserver/plane/authentication/urls.py` | `/auth/mog/` and `/auth/mog/callback/` route bindings |
| `apiserver/plane/authentication/adapter/error.py` | `MOG_NOT_CONFIGURED` (5180) + `MOG_OAUTH_PROVIDER_ERROR` (5181) |
| `apiserver/plane/license/management/commands/configure_instance.py` | `MOG_CLIENT_ID`, `MOG_CLIENT_SECRET`, `MOG_AUTHORIZE_URL`, `MOG_TOKEN_URL`, `MOG_USERINFO_URL` config keys; auto-toggle `IS_MOG_ENABLED=1` when client_id+secret are set |
| `apiserver/plane/license/api/views/instance.py` | Surface `is_mog_enabled` on the public instance config payload (so the frontend could render a "Sign in with MOG" affordance once it's also forked) |
| `.github/workflows/mog-build-images.yml` | Build + push `ghcr.io/mog-deadlock/plane-backend:<tag>` on every push to a `mog-*` branch / tag |

## Configuration shape

Set these env vars in `mog-tracker-infra`'s `.env` (or the prod
equivalent), then `docker compose up -d`:

```
MOG_CLIENT_ID            = plane-tracker
MOG_CLIENT_SECRET        = <high-entropy secret>

# Authorize / token / userinfo URLs default to mogdl.com if unset.
# Override for staging / local-platform-api testing.
MOG_AUTHORIZE_URL        = https://mogdl.com/connect/authorize
MOG_TOKEN_URL            = https://mogdl.com/connect/token
MOG_USERINFO_URL         = https://mogdl.com/connect/userinfo
```

The matching half lives in `mog-platform`'s `OpenIddictClientSeeder`,
which registers Plane as an OIDC client when these are set:

```
OpenIddict__Plane__ClientId          = plane-tracker
OpenIddict__Plane__ClientSecret      = <same as MOG_CLIENT_SECRET>
OpenIddict__Plane__RedirectUri       = https://tasks.mogdl.com/auth/mog/callback/
OpenIddict__Plane__PostLogoutRedirectUri = https://tasks.mogdl.com/   (optional)
```

## Login flow

1. User visits `https://tasks.mogdl.com/auth/mog/`
2. Plane redirects to `https://mogdl.com/connect/authorize?client_id=plane-tracker&...&scope=openid+profile+email+mog:github+offline_access`
3. mogdl.com confirms the Steam-canonical session (or re-prompts Steam login)
4. mogdl.com redirects back to `https://tasks.mogdl.com/auth/mog/callback/?code=...`
5. Plane exchanges the code at `mogdl.com/connect/token`, fetches userinfo, finds-or-creates the `User` row by sub claim
6. Plane sets its own session cookie; user lands on the workspace

Claim mapping (provider/oauth/mog.py → Plane User):

| OIDC claim | Plane field |
|---|---|
| `sub` | `provider_id` (immutable across Steam profile changes) |
| `email` | `email` if surfaced; otherwise synthesized as `<sub>@mog-deadlock.local` |
| `name` / `preferred_username` | `first_name` (split on space) + `last_name` |
| `picture` | `avatar` |
| `github_login` / `github_org_member` / `github_teams` | not stored by Plane today; available in the access token / id token for downstream uses |

## Building + publishing the image

CI publishes on every push to a `mog-*` branch / tag. Tags pushed:

- `ghcr.io/mog-deadlock/plane-backend:<branch-or-tag>`
- `ghcr.io/mog-deadlock/plane-backend:<short-sha>`
- `ghcr.io/mog-deadlock/plane-backend:mog-v0.27.0` (the stable pointer
  `mog-tracker-infra` pins against)

`mog-tracker-infra/docker-compose.yml` will be updated separately to
swap `makeplane/plane-backend:${PLANE_VERSION}` for
`ghcr.io/mog-deadlock/plane-backend:mog-v0.27.0`.

## Frontend / admin / space stay upstream for now

The frontend doesn't yet have a "Sign in with MOG" button — users
visit `/auth/mog/` directly (URL bookmark or a Caddy redirect from
something nicer like `/login/mog`). When we want a button on the
login page we'd fork `web/` too and add it; deferred until the
backend flow is proven end-to-end.

## Tracking upstream

Periodic merge from upstream's stable tag is fine — the changes
above are surgical (one new provider, one new view, ~5 modified
files), shouldn't conflict with most upstream work. If a future
Plane release rewrites the auth backend (it has happened —
v0.20-ish was a big one), expect to redo the adapter shape against
the new base.

## License

This fork inherits Plane's AGPL-3.0 license. We're not redistributing
modified Plane to anyone outside the Mog-Deadlock org; the
`tasks.mogdl.com` instance serves only org members so the AGPL
network-use clause is internal-scope.
