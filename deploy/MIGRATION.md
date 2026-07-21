# Brier — Caddy → nginx edge migration runbook

Move **https://brier.beyondkaira.com** from the shared container-**Caddy** edge to
the host-**nginx** + private-loopback + wildcard-TLS model, **additively and
reversibly**. Nothing here edits a live config until the one windowed cutover in
§5; that step is fully reversible (start Caddy again).

Legend: 👤 = **owner**, needs `sudo` — run by hand. 🤖 = already **committed** by
the agent on branch `deploy/nginx-socket-migration` (no sudo).

## What changes, and why it is safe

| Piece | Before (Caddy) | After (nginx) |
|---|---|---|
| Edge | `pulse-prod-caddy-1` container owns `:443` | host-nginx owns `:443`, one file per subdomain |
| Web bind | `next start -H 0.0.0.0` (public :3000, needs firewall) | `next start -H 127.0.0.1` (private loopback :3000) |
| Reach | container Caddy → host PUBLIC IP `161.97.172.146:3000` | host nginx → `127.0.0.1:3000` |
| TLS | shared Caddy auto-cert | one wildcard `*.beyondkaira.com` cert |
| Web unit | `brier-web.service` (0.0.0.0) — **kept, untouched** | `brier-web-nginx.service` (127.0.0.1) — **new** |
| Worker | `brier-worker.service` — **unchanged** | same unit, same Postgres jobs queue |

The security win: Next.js `next start` cannot bind a unix socket, so it keeps
port **3000** but rebinds to the **private loopback**. Under Caddy the app had to
bind `0.0.0.0` (Caddy ran in a container and reached the app over the host's
public IP), leaving `:3000` internet-reachable — the reason for the port-3000
firewall in `INSTALL.md §5b`. Host-nginx reaches `127.0.0.1` directly, so `:3000`
is no longer public and that firewall workaround becomes unnecessary.

## 🤖 Committed on this branch (no sudo)

- `deploy/nginx/brier.beyondkaira.com.conf` — the nginx `server` block: HTTP→HTTPS
  redirect, TLSv1.2/1.3, the wildcard cert, `server_tokens off`, the forwarded
  headers Caddy set (Host/X-Real-IP/X-Forwarded-For/Proto), HSTS +
  X-Content-Type-Options + X-Frame-Options mirroring `next.config.ts`, and the
  single `location /` → `127.0.0.1:3000` (Brier has no path splits; `/api/health`
  is a route inside the web app).
- `deploy/brier-web-nginx.service` — new web unit, identical to `brier-web.service`
  **except** it binds `-H 127.0.0.1`. `Conflicts=brier-web.service` so the two
  can never co-run on `:3000`.
- `deploy/deployment.sh` — self-contained build → restart-web → health → restart-worker,
  with a bounded curl health gate and `.next`-snapshot rollback.
- `deploy/redis/README.md` — OPTIONAL note on moving the worker's Postgres jobs
  queue to the shared redis (document-only; the worker is unchanged).

The existing `brier-web.service`, `brier-worker.service`, `docker-compose.yml`,
`deploy/Caddyfile.brier.snippet`, and `INSTALL.md` are **untouched** — the live
Caddy path keeps working until you choose to cut over.

---

## 1. 👤 Host prerequisites (once per host — likely already done for other apps)

```bash
sudo apt-get update && sudo apt-get install -y nginx
sudo systemctl enable --now nginx
```

Wildcard TLS via certbot DNS-01 (once per host; covers EVERY `*.beyondkaira.com`
subdomain — no per-site cert step):

```bash
sudo apt-get install -y certbot python3-certbot-dns-cloudflare
sudo install -d -m700 /root/.secrets
printf 'dns_cloudflare_api_token = %s\n' "$CF_TOKEN" | sudo tee /root/.secrets/cloudflare.ini >/dev/null
sudo chmod 600 /root/.secrets/cloudflare.ini
sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials /root/.secrets/cloudflare.ini \
  -d '*.beyondkaira.com' -d beyondkaira.com
# Verify the cert the nginx block references exists:
sudo ls -l /etc/letsencrypt/live/beyondkaira.com/fullchain.pem
```

DNS already resolves (`brier.beyondkaira.com A 161.97.172.146`) — the site is live
today, so no DNS change is needed.

## 2. 👤 Env source (already exists) + build-time origin

Both the old and new web units read the same root-owned file
`/etc/brier/brier.env` (created for `brier-web.service` — see `INSTALL.md §3`).
The new unit reuses it as-is; **no new keys** are introduced by this migration.
See `.env.production.example` for the full key list (values are never committed).

The public origin is baked into `.next` at build time; the host-specific,
gitignored file must exist before `deployment.sh` builds:

```bash
printf 'NEXT_PUBLIC_SITE_URL=https://brier.beyondkaira.com\n' \
  > /home/aytek/repo/brier-claude/apps/web/.env.production.local
```

## 3. 👤 Install the new web unit + a scoped sudoers rule for deploys

```bash
cd /home/aytek/repo/brier-claude
sudo cp deploy/brier-web-nginx.service /etc/systemd/system/
sudo systemctl daemon-reload
# Do NOT enable --now yet — brier-web.service still owns :3000. Start it in §5.
```

`deployment.sh` restarts the web + worker units; grant exactly those two, so
deploys need no interactive sudo:

```bash
sudo tee /etc/sudoers.d/deploy-brier >/dev/null <<'EOF'
aytek ALL=(root) NOPASSWD: /usr/bin/systemctl restart brier-web-nginx, /usr/bin/systemctl restart brier-worker, /usr/bin/systemctl is-active brier-worker, /usr/bin/systemctl cat brier-web-nginx, /usr/bin/systemctl cat brier-worker
sudo chmod 440 /etc/sudoers.d/deploy-brier
EOF
sudo chmod 440 /etc/sudoers.d/deploy-brier
sudo visudo -c    # validate the sudoers file
```

## 4. 👤 Install the nginx site (does NOT touch Caddy or :443 yet)

Dropping the file + reloading nginx is safe **as long as nginx is not yet bound
to :443** (Caddy still owns it). If nginx already fronts other beyondkaira.com
subdomains, this just adds one more `server` block; `nginx -t` rejects a bad
config before any reload.

```bash
cd /home/aytek/repo/brier-claude
sudo cp deploy/nginx/brier.beyondkaira.com.conf \
        /etc/nginx/sites-available/brier.beyondkaira.com.conf
sudo ln -sfn /etc/nginx/sites-available/brier.beyondkaira.com.conf \
             /etc/nginx/sites-enabled/brier.beyondkaira.com.conf
sudo nginx -t          # MUST pass — a bad config is rejected here, never served
sudo systemctl reload nginx
```

---

## 5. 👤 The cutover (ONE maintenance window — reversible)

nginx and Caddy cannot both own `:443`. This is the only step with downtime
(seconds). It swaps the web bind 0.0.0.0 → 127.0.0.1 and the edge Caddy → nginx
together, because the loopback-bound app is only reachable once nginx fronts it.

> If this shared Caddy also fronts the owner's OTHER prod apps, build nginx
> `server` blocks for **every** current Caddy site first and do them together —
> stopping Caddy frees `:443` for all of them at once. (See the blueprint
> `deploy/INSTALL.md §9`.) The steps below are the brier-specific slice.

```bash
cd /home/aytek/repo/brier-claude

# 1) Swap the web unit: stop the 0.0.0.0 unit, start the 127.0.0.1 unit.
#    Conflicts= makes this mutually exclusive; both target :3000.
sudo systemctl disable --now brier-web            # old public-bind unit
sudo systemctl enable  --now brier-web-nginx      # new loopback-bind unit
curl -fsS http://127.0.0.1:3000/api/health -w '  loopback %{http_code}\n'   # expect ok/200

# 2) Free :443 from Caddy, hand it to nginx.
sudo docker stop pulse-prod-caddy-1               # Caddy releases :443 (config untouched)
sudo systemctl reload nginx                       # nginx now serves :443 for brier

# 3) Verify the public edge end to end.
curl -fsS https://brier.beyondkaira.com/            -o /dev/null -w 'site   %{http_code}\n'
curl -fsS https://brier.beyondkaira.com/api/health              -w '  health %{http_code}\n'
curl -sI  https://brier.beyondkaira.com/ | grep -i 'strict-transport\|content-security\|x-frame'
```

### Rollback (any failure in §5) — back to Caddy, unchanged

```bash
sudo docker start pulse-prod-caddy-1              # Caddy retakes :443 (its config never changed)
sudo systemctl disable --now brier-web-nginx      # stop the loopback unit
sudo systemctl enable  --now brier-web            # restore the 0.0.0.0 unit Caddy expects
curl -fsS https://brier.beyondkaira.com/ -o /dev/null -w 'site %{http_code}\n'
```

Because the migration is additive, rollback needs **no file edits** — it only
starts the container and unit that were already there. Keep `brier-web.service`,
the Caddy snippet, and (optionally) the port-3000 firewall until the nginx edge
is proven over a few days.

## 6. 👤 After the cutover is proven

- The port-3000 firewall (`INSTALL.md §5b`) is now redundant — `:3000` is
  loopback-only. You may leave it (harmless) or remove it once confident.
- `certbot renew` auto-replaces the wildcard cert (systemd timer); nginx picks it
  up on the next reload. Confirm: `sudo systemctl list-timers 'certbot*'`.

## 7. 🤖 Routine deploys after cutover

From the repo on the box:

```bash
cd /home/aytek/repo/brier-claude
deploy/deployment.sh --check     # asserts config + units, changes nothing
deploy/deployment.sh             # build → restart web → health → restart worker
```

`deployment.sh` snapshots `.next` before building and, on a failed restart or a
health probe that never returns `{"status":"ok"}`, restores the snapshot,
restarts the web unit, and re-checks health (bounded, hard-fail timeout).

---

## Environment keys

No new keys. The migration reuses `/etc/brier/brier.env` and
`apps/web/.env.production.local`; every key is documented (names only, never
values) in the committed `.env.production.example`. Secrets stay out of the repo
(`.env` / `.env.*` are gitignored except the `*.example` templates).
