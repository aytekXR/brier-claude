# Brier — production deploy runbook (this host)

Host-specific install steps to turn the **live** site at **https://brier.beyondkaira.com**
into a *secure, supervised, monitored* deployment. This is **Phase 1** of the go-live
worklist in `next-prompt.md` — it changes **ops, not data**; the public board keeps showing
the 3 fixture analysts (that is the separate **Phase 2** data decision).

## This host (read first)

- **This box *is* the VPS.** `161.97.172.146` = `brier.beyondkaira.com`. OS user **`aytek`**;
  repo at **`/home/aytek/repo/brier-claude`** (`$REPO`).
- **The agent has no sudo.** Every `sudo` / `systemctl` / `docker` / dashboard step below is
  marked **👤 owner**. Steps marked **🤖** are already committed by the agent (noted inline).
- **Docker = Engine + systemd** (no Desktop): wrap compose in `sg docker -c '…'`.
- **`node` is nvm** (`/home/aytek/.local/bin/node` → `~/.nvm/…`) and is **not** on systemd's
  default `PATH`. `deploy/brier-web.service` already prepends it via `Environment=PATH=…` —
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
- `deploy/brier-worker.service` — edited for this host (`aytek`, repo path, `.venv`).
- `deploy/Caddyfile.brier.snippet` — committed copy of the live Caddy block + `header -Server`.
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
BRIER_DATABASE_URL=postgresql://brier:brier@127.0.0.1:5432/brier   # rotate in step 5
BRIER_RESEND_API_KEY=...        # see step 8 (currently returns 401)
BRIER_DISPUTE_FROM_EMAIL=disputes@brier.beyondkaira.com
BRIER_BUTTONDOWN_API_KEY=...
# worker keys (idle now, used in Phase 2): BRIER_ANTHROPIC_API_KEY, BRIER_YOUTUBE_API_KEY,
# BRIER_COINGECKO_API_KEY, BRIER_DEEPGRAM_API_KEY, BRIER_BETTER_STACK_TOKEN / BRIER_SENTRY_DSN
```

> Setting `BRIER_RESEND_API_KEY` / `BRIER_BUTTONDOWN_API_KEY` here is what stops the **silent
> drop** of dispute email + newsletter signups (without them the web process falls back to
> `FakeNotifier` / `FakeSubscriber`). Email still needs step 8 (Resend domain verification).

## 4. 👤 Cut over to systemd (one maintenance window)

Order matters and is deliberate: drop the `@reboot` launcher **first** (so it can't win a boot
race against the new service later, especially after step 5 rotates the DB password the old
launcher hardcodes), stop the old server, rebuild while nothing serves `.next`, then start the
supervised units. Expect ~1–2 min of downtime during the build — a one-time, low-traffic cutover.

```bash
cd $REPO

# 1) Remove the @reboot launcher FIRST (closes the post-rotation boot race in step 5):
crontab -e        # delete the line: @reboot /home/aytek/brier-web-start.sh

# 2) Stop the old cron-launched server (frees :3000; -9 skips the graceful-drain tail so the
#    new unit can bind immediately, with no EADDRINUSE / restart-loop race):
kill -9 "$(ss -ltnp 'sport = :3000' | grep -oP 'pid=\K[0-9]+' | head -1)"

# 3) Rebuild NOW — nothing is serving from .next, so there is no chunk-mismatch risk:
make web-build                    # bakes in /api/health + the redirects

# 4) Install + start the supervised units:
sudo cp deploy/brier-web.service deploy/brier-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brier-web      # binds :3000 on the fresh build
sudo systemctl enable --now brier-worker   # idle is correct (empty jobs table, no scheduler)

# 5) Verify:
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
read -rsp 'New DB password: ' NEWPW; echo      # read silently — keeps it out of shell history
sg docker -c "docker compose exec -T db psql -U brier -d brier -c \"ALTER USER brier PASSWORD '$NEWPW'\""

# Point every consumer at the rotated password (BRIER_DATABASE_URL=...@127.0.0.1:5432/brier):
#   - /etc/brier/brier.env   (systemd services)
#   - $REPO/.env             (worker / scripts when sourced by hand)
sudo $EDITOR /etc/brier/brier.env
$EDITOR $REPO/.env
unset NEWPW
sudo systemctl restart brier-web brier-worker

# Verify loopback-only + the app still connects:
ss -ltnp | grep 5432            # expect ONLY 127.0.0.1:5432 (no 0.0.0.0 / [::])
curl -fsS https://brier.beyondkaira.com/ -o /dev/null -w 'site %{http_code}\n'
```

### 5b. Web — firewall port 3000 from the public internet

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
nothing (Caddy fronts `:3000`). Safe to kill once `:3000` is supervised by systemd:

```bash
kill "$(ss -ltnp 'sport = :3100' | grep -oP 'pid=\K[0-9]+' | head -1)"
```

## 8. 👤 Caddy: strip the `Server` header (optional polish)

The site routing already works (the live block is in the shared `ams-pulse` repo:
`deploy/config/Caddyfile.prod`, the `brier.{$PULSE_DOMAIN}` block; backup `…bak-brier`). To add
`header -Server` (committed copy: `deploy/Caddyfile.brier.snippet`), edit that block, then —
because this Caddy **also fronts the owner's other prod apps** — **validate before reload**:

```bash
cd $REPO/../ams-pulse
# add `header -Server` to the brier.{$PULSE_DOMAIN} block, then:
sg docker -c 'docker exec pulse-prod-caddy-1 caddy validate --config /etc/caddy/Caddyfile'
sg docker -c 'docker exec pulse-prod-caddy-1 caddy reload  --config /etc/caddy/Caddyfile'   # atomic; a bad config is rejected, never dropped
```

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
