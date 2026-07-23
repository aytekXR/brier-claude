# Brier — production deploy runbook (this host)

> **STATUS: Phase 1 COMPLETE — and the edge has since moved to host-nginx**
> (`deploy/MIGRATION.md`). Current production:
> - Edge: host **nginx** → `127.0.0.1:3000` (`deploy/nginx/brier.beyondkaira.com.conf`,
>   installed in `/etc/nginx/sites-available/`); TLS is the shared `beyondkaira.com`
>   SAN cert (certbot --nginx, HTTP-01, auto-renew).
> - Web: systemd **`brier-web-nginx.service`** (loopback-only `next start`).
>   The caddy-era `brier-web.service` (0.0.0.0) is **deleted**.
> - Worker: systemd **`brier-worker.service`**.
> - DB: compose container **`brier-db`** (`docker-compose.yml`, `127.0.0.1:5432`,
>   `restart: unless-stopped`).
> - Env: `/etc/brier/brier.env` (root-owned, chmod 600 — reference it, never print it).
> - Routine deploys: `deploy/deployment.sh` (see `MIGRATION.md §7`).
>
> Caddy no longer fronts this site; the caddy-era steps below (§5b firewall, §8)
> are marked **RETIRED** and kept only as the record of what was done.

Host-specific install steps that turned the **live** site at **https://brier.beyondkaira.com**
into a *secure, supervised, monitored* deployment. This was **Phase 1** of the go-live
worklist in `next-prompt.md` — it changed **ops, not data**; the public board keeps showing
the 3 fixture analysts (that is the separate **Phase 2** data decision).

## This host (read first)

- **This box *is* the VPS.** `161.97.172.146` = `brier.beyondkaira.com`. OS user **`aytek`**;
  repo at **`/home/aytek/repo/depricated/brier-claude`** (`$REPO`).
- **The agent has no sudo.** Every `sudo` / `systemctl` / `docker` / dashboard step below is
  marked **👤 owner**. Steps marked **🤖** are already committed by the agent (noted inline).
- **Docker = Engine + systemd** (no Desktop): wrap compose in `sg docker -c '…'`.
- **`node` is nvm** (`/home/aytek/.local/bin/node` → `~/.nvm/…`) and is **not** on systemd's
  default `PATH`. `deploy/brier-web-nginx.service` already prepends it via `Environment=PATH=…` —
  do not remove that line or the unit won't start.
- **Do NOT run `make web-build` / `make ci` while the live `next start` is serving.** They
  rebuild `.next` underneath the running server and can break it with chunk mismatches.
  Rebuild only inside the maintenance window (step 2), then restart the service.
  `make check` is safe to run live (no build, no DB writes that survive — committing tests
  clean up / are idempotent).

## What the agent already changed (🤖, committed)

- `docker-compose.yml`: Postgres port `"5432:5432"` → **`"127.0.0.1:5432:5432"`** (loopback only).
- `.env`: permissions tightened to **`600`** (was world-readable `664`).
- `deploy/brier-web.service` — new systemd unit (PATH-fixed for nvm node).
  *(Since superseded by `deploy/brier-web-nginx.service` and deleted — see MIGRATION.md.)*
- `deploy/brier-worker.service` — edited for this host (`aytek`, repo path, `.venv`).
- `deploy/Caddyfile.brier.snippet` — committed copy of the live Caddy block + `header -Server`.
  *(Since deleted — Caddy no longer fronts this site.)*
- `apps/web/app/api/health/route.ts` + `lib/db.ts:pingDb()` — `GET /api/health` (200/503).
- `apps/web/next.config.ts` — `/leaderboard → /` (308) and `/newsletter → /` (307) redirects.
- `make start-web` — fallback launcher for hosts without systemd.

The rest of this file is the **👤 owner** runbook. Do the steps **in order** — the sequence
minimizes downtime (one ~30–60 s web cutover) and avoids breaking the live DB connection.

---

## 1. (already 🤖) Loopback DB binding is committed — recreate happens in step 5

No action yet. The compose edit is inert until the container is recreated; doing that *now*
(before the web service reads a rotated password) would break the live site. The DB lockdown
is performed together with the password rotation in **step 5**, after the web service owns its
env from one source.

## 2. 👤 Sanity-check the gate (optional)

`make check` is safe to run against the live box (no build; the committing tests are idempotent
or clean up, so the live board is untouched):

```bash
cd $REPO
env -u BRIER_ENV make check        # expect "944 passed, 1 skipped"
```

> The production rebuild that bakes in `/api/health` + the redirects happens **inside the
> step-4 cutover window — after the old server is stopped** — so `next build` never overwrites
> `.next` underneath a running `next start` (which would cause chunk-mismatch 500s on the live
> site). Do **not** run `make web-build` while the current server is serving.

## 3. 👤 Create the single env source `/etc/brier/brier.env`

Both services read this one root-owned file (keys never enter the repo or `ps`). Fill it from
the committed template `.env.production.example`, copying the real values from `$REPO/.env`:

```bash
sudo install -d -m755 /etc/brier
sudo install -m600 /dev/null /etc/brier/brier.env
sudo $EDITOR /etc/brier/brier.env
```

Minimum keys for Phase 1 (web + idle worker):

```
BRIER_ENV=production
NODE_ENV=production
NEXT_PUBLIC_SITE_URL=https://brier.beyondkaira.com
BRIER_DATABASE_URL=postgresql://brier:brier@127.0.0.1:5432/brier
BRIER_RESEND_API_KEY=
BRIER_DISPUTE_FROM_EMAIL=disputes@brier.beyondkaira.com
BRIER_BUTTONDOWN_API_KEY=
# worker keys (idle now, used in Phase 2): BRIER_ANTHROPIC_API_KEY, BRIER_YOUTUBE_API_KEY,
# BRIER_COINGECKO_API_KEY, BRIER_DEEPGRAM_API_KEY, BRIER_BETTER_STACK_TOKEN / BRIER_SENTRY_DSN
```

> **Do NOT put an inline `# …` comment after a value.** systemd's `EnvironmentFile` parser keeps
> everything after `=` as the value (only *whole-line* `#`/`;` lines are ignored), so a line like
> `BRIER_DATABASE_URL=…/brier   # rotate later` feeds the comment to the pg client as part of the
> DSN and **crash-loops** the service. (The `# worker keys …` lines above are whole-line comments,
> so they are fine.) Keep `127.0.0.1`, not `localhost`, on the DSN — see step 5's note on IPv6.
> `BRIER_DATABASE_URL` receives its real password in **step 5**; `BRIER_RESEND_API_KEY` currently
> returns 401 (**step 9**).
>
> Setting `BRIER_RESEND_API_KEY` / `BRIER_BUTTONDOWN_API_KEY` here is what stops the **silent
> drop** of dispute email + newsletter signups (without them the web process falls back to
> `FakeNotifier` / `FakeSubscriber`). Email still needs step 9 (Resend domain verification).

## 4. 👤 Cut over to systemd (one maintenance window)

> **As executed in the Caddy era.** The unit installed here, `brier-web.service`,
> has since been replaced by `brier-web-nginx.service` and deleted from the repo
> (MIGRATION.md §5). To (re)install today's units:
> `sudo cp deploy/brier-web-nginx.service deploy/brier-worker.service /etc/systemd/system/`
> then `sudo systemctl daemon-reload`.

Order matters and is deliberate: drop the `@reboot` launcher **first** (so it can't win a boot
race against the new service later, especially after step 5 rotates the DB password the old
launcher hardcodes), stop the old server, rebuild while nothing serves `.next`, then start the
supervised units. Expect ~1–2 min of downtime during the build — a one-time, low-traffic cutover.

```bash
cd $REPO

# 1) Remove the @reboot launcher FIRST (closes the post-rotation boot race in step 5):
crontab -e        # delete the line: @reboot /home/aytek/brier-web-start.sh

# 2) Stop the old cron-launched server (frees :3000; -9 skips the graceful-drain tail so the
#    new unit can bind immediately, with no EADDRINUSE / restart-loop race). Guarded so an
#    already-stopped server can't abort the cutover on a non-zero exit:
PID=$(ss -ltnp 'sport = :3000' | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$PID" ] && kill -9 "$PID" || echo ':3000 already free — continuing'

# 3) Bake the BUILD-TIME public origin. `next build` inlines NEXT_PUBLIC_SITE_URL into .next
#    (sitemap.xml, robots.txt, canonical/OG URLs); the systemd EnvironmentFile only covers the
#    server-side RUNTIME read, so without this the static URLs bake to http://localhost:3000.
#    apps/web/.env.production.local is gitignored + host-specific (the .env.production.example pattern):
printf 'NEXT_PUBLIC_SITE_URL=https://brier.beyondkaira.com\n' > apps/web/.env.production.local

# 4) Create/refresh the worker venv + rebuild web NOW — nothing serves .next, so no chunk-mismatch:
make install-pipeline             # creates services/pipeline/.venv (brier-worker ExecStart needs it)
make web-build                    # bakes in /api/health + the redirects + the real origin

# 5) Install + start the supervised units:
sudo cp deploy/brier-web.service deploy/brier-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brier-web      # binds :3000 on the fresh build
sudo systemctl enable --now brier-worker   # idle is correct (empty jobs table, no scheduler)

# 6) Verify:
systemctl status brier-web brier-worker --no-pager
journalctl -u brier-web -n 30 --no-pager
curl -fsS https://brier.beyondkaira.com/ -o /dev/null -w 'site %{http_code}\n'
```

> **Fallback (no systemd available):** load the env, then use the Makefile target —
> `set -a && source /etc/brier/brier.env && set +a && make start-web &` — it serves the same
> build on :3000 (unsupervised; still needs the step-5b firewall).

## 5. 👤 Lock the network down (DB loopback + rotate; firewall port 3000)

### 5a. Database — loopback binding + rotate the password

Recreate the container (picks up the `127.0.0.1` binding) and rotate the password **inside
psql** — the named volume persists, so changing `POSTGRES_PASSWORD` in compose alone is a
no-op. Do this *after* step 4: the `@reboot` launcher (now removed) hardcoded the old
`brier:brier` URL, so rotation is only safe once that launcher is gone and the systemd services
own their env.

```bash
cd $REPO
sg docker -c 'docker compose up -d db'         # recreate with the loopback binding

# Pick a password with NO single quote (') and no shell metacharacters — it is embedded in
# single-quoted SQL below, so a quote would corrupt the ALTER and leave the password UNROTATED
# (silently). Easiest safe choice is a hex token (alphanumeric only):
NEWPW=$(openssl rand -hex 24)                  # or: read -rsp 'New DB password: ' NEWPW; echo
sg docker -c "docker compose exec -T db psql -U brier -d brier -c \"ALTER USER brier PASSWORD '$NEWPW'\""
echo "New DB password (store in your secret manager NOW): $NEWPW"

# Point every consumer at the rotated password (BRIER_DATABASE_URL=...@127.0.0.1:5432/brier):
#   - /etc/brier/brier.env   (systemd services)
#   - $REPO/.env             (worker / scripts when sourced by hand)
sudo $EDITOR /etc/brier/brier.env
$EDITOR $REPO/.env
unset NEWPW
sudo systemctl restart brier-web brier-worker

# Verify loopback-only + the app still connects. The health 200 also proves the rotation took:
# a failed ALTER would leave the services unable to authenticate, and /api/health would 503.
ss -ltnp | grep 5432            # expect ONLY 127.0.0.1:5432 (no 0.0.0.0 / [::])
curl -fsS https://brier.beyondkaira.com/         -o /dev/null -w 'site   %{http_code}\n'
curl -fsS https://brier.beyondkaira.com/api/health             -w '  health %{http_code}\n'
```

### 5b. Web — firewall port 3000 from the public internet — **RETIRED**

> Under the nginx edge the web unit binds `127.0.0.1:3000` (loopback-only), so
> `:3000` is not internet-reachable and this firewall is unnecessary. If the
> caddy-era iptables rules below are still present they are harmless and may be
> removed. Kept as the record of the Caddy-era exposure and its mitigation.

`brier-web.service` (and the `start-web` fallback) run `next start -H 0.0.0.0`, and the shared
Caddy reaches the app via the **public IP** `161.97.172.146:3000` (Caddy runs in a container and
cannot use the host's `127.0.0.1`). So `:3000` is reachable from the internet, serving the **raw
app without TLS or the security headers** Caddy/next.config add. (This exposure predates Phase 1
— the old launcher also bound `0.0.0.0` — but Phase 1 is where it gets closed.) Block external
access, allowing only loopback + the Docker bridge where Caddy lives:

```bash
# Prefer the provider's cloud firewall if you have one. Host-level (IPv4 + IPv6):
sudo iptables  -I INPUT -p tcp --dport 3000 -i lo -j ACCEPT
sudo iptables  -I INPUT -p tcp --dport 3000 -s 172.16.0.0/12 -j ACCEPT    # docker bridge range
sudo iptables  -A INPUT -p tcp --dport 3000 -j DROP
sudo ip6tables -A INPUT -p tcp --dport 3000 -j DROP
sudo netfilter-persistent save                                            # survive reboot

# Verify from OFF-box: `curl --max-time 5 http://161.97.172.146:3000/` should refuse/time out,
# while https://brier.beyondkaira.com/ (via Caddy) still returns 200.
```

> Confirm Caddy's container subnet is inside `172.16.0.0/12` (`docker network inspect` the
> network `pulse-prod-caddy-1` is attached to); widen/adjust the `-s` rule if it uses a custom
> subnet. A tighter alternative — bind Next to the Docker bridge gateway IP and point Caddy
> there — is deferred because it edits the shared ams-pulse Caddy config.

> `config.py DEFAULT_DATABASE_URL` stays `brier:brier` — that is the **dev** default; never
> rely on it in prod (production reads the rotated `BRIER_DATABASE_URL`).

## 6. 👤 Verify `/api/health` + wire the uptime monitor

```bash
curl -fsS https://brier.beyondkaira.com/api/health      # expect {"status":"ok"}  (503 on DB down)
```

Register the URL with the uptime monitor (`BRIER_BETTER_STACK_TOKEN`) so a 503 / outage pages.

## 7. 👤 Kill the stale `:3100` server

A second `next start` (pid was `256341`, on `:3100` since Jun 15) wastes ~230 MB and serves
nothing (the edge fronts `:3000`). Safe to kill once `:3000` is supervised by systemd:

```bash
kill "$(ss -ltnp 'sport = :3100' | grep -oP 'pid=\K[0-9]+' | head -1)"
```

## 8. 👤 Caddy: strip the `Server` header — **RETIRED**

Caddy no longer fronts this site: the edge is host nginx, and
`deploy/nginx/brier.beyondkaira.com.conf` already sets `server_tokens off` (the
nginx equivalent of this polish). The committed Caddy snippet
(`deploy/Caddyfile.brier.snippet`) has been deleted along with the rest of the
caddy-era artifacts.

## 9. 👤 Fix Resend before trusting email

The key currently returns **HTTP 401** (invalid or send-only-scoped) and the sending domain
needs **SPF/DKIM** verified in the Resend dashboard for `brier.beyondkaira.com`. Until both are
done, dispute/adjudication email fails even with the key set. (Buttondown likewise needs its
sender verified.) After fixing: file one test dispute + one newsletter signup and confirm
delivery.

---

## Phase-1 done = testable live

A secure (loopback-only DB, rotated creds, `600` secrets), supervised (systemd + auto-restart,
reboot-survivable), monitored (`/api/health` + uptime) production site with working
email/signups — **still showing the fixture board**. That fixture-vs-real choice is the
**Phase 2** data decision in `next-prompt.md` — **stop and get an owner decision before
ingesting real analysts** (publishing synthetic analysts as real is the one thing that must
not happen on a public launch).
