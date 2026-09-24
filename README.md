## docker-home

Docker Compose stacks for `kiwisvr01`, my homelab server. Each top-level directory is an
independent stack (its own `docker-compose.yml`, `.env`, and any config it needs).

### Networking

- **Traefik** (`traefik/`) is the reverse proxy / TLS termination for everything, listening on
  `80`/`443` and issuing Let's Encrypt certs. Services opt in via `traefik.*` Docker labels.
- Almost every stack joins the external `proxy` Docker network (created out-of-band, not by any
  compose file here — `docker network create proxy --ipv6`) so Traefik can route to them.
- **cloudflared** (`cloudflared/`) runs a Cloudflare Tunnel for the handful of services exposed
  to the internet (currently `auth`, `jellyfin`, `seerr`), fronted by Cloudflare Access.
- **pihole** (`pihole/`) is internal DNS/adblock for the LAN.

### Auth

**Authentik** (`authentik/`, `auth.loganhill.nz`) is the SSO/identity provider, replacing a
former Authelia+lldap setup (decommissioned). Most internal apps are gated by Traefik's
`authentik@docker` forward-auth middleware. Two exceptions, because neither app understands
forward-auth headers or works with it for native clients:
- **Jellyfin** does its own OIDC via the `JellyfinSecurity` plugin instead of forward-auth.
- **Seerr** has no SSO support at all and uses its native login.

Guest access to Jellyfin/Seerr is handled by Cloudflare Access, itself backed by Authentik OIDC.

`auth/` is a leftover from the old Authelia/lldap stack — no compose file anymore, just an inert
`.env` with old secrets. Rollback data still sits on disk at `/srv/authelia` and `/srv/lldap` and
can be purged once nothing depends on it being there.

### Stacks

| Directory | What it runs | URL |
|---|---|---|
| `traefik/` | Reverse proxy, TLS termination | `:80`/`:443`, dashboard on `:8082` |
| `cloudflared/` | Cloudflare Tunnel client | — |
| `authentik/` | Authentik server/worker + its own Postgres/Redis | `auth.loganhill.nz` |
| `pihole/` | DNS + adblock | `pihole.loganhill.nz` |
| `jellyfin/` | Jellyfin + Sonarr, Radarr, Lidarr, Prowlarr, Deluge, FlareSolverr, Seerr | `jellyfin.loganhill.nz`, `seerr.loganhill.nz` |
| `immich/` | Immich photo management | `immich.loganhill.nz` |
| `monitoring/` | Grafana, Prometheus, and exporters (pihole, Mikrotik, node, ZFS, iDRAC) | `grafana.loganhill.nz` |
| `unifi/` | UniFi Network Application + Mongo | `unifi.loganhill.nz` |
| `minecraft/` | Minecraft server (CurseForge modpack) + BlueMap | `mc.loganhill.nz` |
| `watchtower/` | Watches for image updates, monitor-only, emails on findings | — |
| `ntfy/` | Reserved for a future ntfy deployment; no compose file yet | — |
| `auth/` | Decommissioned Authelia/lldap remnant (see above) | — |

### Secrets

Each stack that needs credentials keeps them in its own `.env` (gitignored); where one exists,
copy the sibling `.example.env` and fill it in. `.gitignore` also excludes a few config files
that carry live secrets outside of `.env` (e.g. `monitoring/idrac.yml`, `pihole/.env`).

### Updates

Watchtower checks for new images across all stacks but is deliberately monitor-only — it emails
`me@loganhill.nz` instead of auto-restarting containers, since blind auto-updates risk breaking
things like Postgres or Traefik.
