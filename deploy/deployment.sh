#!/usr/bin/env bash
# =============================================================================
# deployment.sh — ON-BOX build + supervised restart for Brier behind host-nginx.
#
# WHAT IT DOES (the six steps, in order)
#   1. preflight  tools present, git checkout, config sane, .env.production.local
#   2. build      snapshot the live .next as a rollback point, then `make web-build`
#   3. rollback   the snapshot from step 2 IS the rollback point (recorded)
#   4. (no data backup — a Next build is stateless; the DB is untouched here)
#   5. apply      restart the web unit (brier-web-nginx) so it serves the new .next
#   6. health     bounded curl loop against the PUBLIC url asserting a real body
#                 marker; THEN restart the worker unit. A failed restart or health
#                 check restores the snapshot, restarts web, and re-checks health.
#
# SELF-CONTAINED: no bin/repo, no repo_cli, no blueprint health-check.sh. The
# health gate is this file's own bounded curl loop (below), asserting the
# {"status":"ok"} marker in the body of https://brier.beyondkaira.com/api/health
# — not merely "it answered" — with a hard-fail timeout.
#
# THE `set -e` BUG THIS FILE IS SHAPED AROUND
#   Under `set -euo pipefail` a bare failing command exits the script, so a
#   rollback written as `step; if [ $? -ne 0 ]; then rollback; fi` is DEAD CODE.
#   Every mutating step here is `if ! <step>; then rollback; exit 1; fi`, because
#   a command in an `if` condition is exempt from `set -e`. (The lesson from
#   yanki's deploy.sh.)
#
# RUN MODEL: this runs ON the VPS (this box IS brier.beyondkaira.com — see
# deploy/MIGRATION.md / INSTALL.md). The web/worker are systemd units; restarting
# them needs a scoped, NOPASSWD sudoers rule (documented in MIGRATION.md), which
# is why SYSTEMCTL defaults to `sudo systemctl`.
#
# CONFIG (env-overridable; defaults are correct for THIS host):
#   WEB_UNIT       systemd unit for the web app   (default brier-web-nginx)
#   WORKER_UNIT    systemd unit for the worker    (default brier-worker)
#   SYSTEMCTL      how to drive systemd           (default "sudo systemctl")
#   HEALTH_URL     public probe url               (default https://brier.beyondkaira.com/api/health)
#   HEALTH_EXPECT  required marker in the body    (default "status":"ok")
#   HEALTH_TIMEOUT seconds to wait for health     (default 90)
#   BUILD_CMD      the web build                  (default "make web-build")
#
# EXIT: 0 built, live, healthy · 1 failed (rolled back where possible) · 2 usage
# =============================================================================
set -euo pipefail

ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WEB_DIR="$ROOT/apps/web"
NEXT_DIR="$WEB_DIR/.next"
NEXT_ROLLBACK="$WEB_DIR/.next.rollback"

WEB_UNIT="${WEB_UNIT:-brier-web-nginx}"
WORKER_UNIT="${WORKER_UNIT:-brier-worker}"
SYSTEMCTL="${SYSTEMCTL:-sudo systemctl}"
HEALTH_URL="${HEALTH_URL:-https://brier.beyondkaira.com/api/health}"
HEALTH_EXPECT="${HEALTH_EXPECT:-\"status\":\"ok\"}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"
BUILD_CMD="${BUILD_CMD:-make web-build}"

CHECK_ONLY=0

usage() {
  cat <<'USAGE'
usage: deploy/deployment.sh [--check]

  --check   run every preflight assertion, print the plan (build cmd, units,
            health url + marker) and change NOTHING — no build, no restart.
            Run this first. It exits non-zero if the host is not configured yet
            (e.g. the systemd units are not installed) — that is expected before
            the owner completes the deploy/MIGRATION.md setup steps.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check | --dry-run) CHECK_ONLY=1 ;;
    -h | --help) usage; exit 0 ;;
    *) printf 'deployment: unknown argument %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n== %s\n' "$1"; }
info() { printf '   %s\n' "$1"; }
oops() { printf 'deployment: %s\n' "$1" >&2; }

# --- the health gate: a bounded loop asserting a REAL body marker -------------
# Returns 0 only when the public url returns a body CONTAINING $HEALTH_EXPECT
# within $HEALTH_TIMEOUT seconds. `curl -f` rejects non-2xx (a 503 from a DB-down
# health route fails the grep AND the -f), so this asserts the DB round-trips,
# not merely that something answered on :443.
health_check() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) body=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    body="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
    if printf '%s' "$body" | grep -qF "$HEALTH_EXPECT"; then
      info "health: ${HEALTH_URL} returned the '${HEALTH_EXPECT}' marker"
      return 0
    fi
    sleep 3
  done
  oops "health: ${HEALTH_URL} never returned '${HEALTH_EXPECT}' within ${HEALTH_TIMEOUT}s"
  oops "  last body seen: ${body:-<none / connection failed>}"
  return 1
}

# --- rollback: restore the pre-build .next, restart web, re-verify health -----
# Defined before the first step that can call it; invoked ONLY from inside `if !`.
rollback() {
  if [ ! -d "$NEXT_ROLLBACK" ]; then
    oops "no .next snapshot to roll back to (first build, or build never started)."
    oops "  the web unit is serving whatever .next is on disk. Inspect:"
    oops "  journalctl -u ${WEB_UNIT} -n 50 --no-pager"
    return 1
  fi
  printf '\n== rolling back: restoring the pre-build .next\n' >&2
  rm -rf "$NEXT_DIR"
  if ! mv -T "$NEXT_ROLLBACK" "$NEXT_DIR"; then
    oops "could NOT restore the .next snapshot. Manual intervention required now."
    return 1
  fi
  if ! $SYSTEMCTL restart "$WEB_UNIT"; then
    oops "restored .next but the ${WEB_UNIT} restart FAILED. Manual intervention."
    return 1
  fi
  if ! health_check; then
    oops "restored .next + restarted ${WEB_UNIT} but it is NOT healthy. Manual intervention."
    return 1
  fi
  info "rollback complete — the previous build is live and healthy"
  return 0
}

# ---------------------------------------------------------------------------
say "1/6 preflight"
# ---------------------------------------------------------------------------
for tool in git curl make; do
  command -v "$tool" >/dev/null 2>&1 || { oops "$tool is not on PATH"; exit 1; }
done
git rev-parse --git-dir >/dev/null 2>&1 || {
  oops "not a git checkout — there is no sha to describe or roll back to"; exit 1;
}
[ -d "$WEB_DIR" ] || { oops "web dir not found: $WEB_DIR"; exit 1; }

# The build inlines NEXT_PUBLIC_SITE_URL into .next; without it the static origin
# bakes to http://localhost:3000 (see INSTALL.md step 4). Warn, do not hard-fail
# (the systemd EnvironmentFile still covers the runtime read).
if [ ! -f "$WEB_DIR/.env.production.local" ]; then
  info "WARN: $WEB_DIR/.env.production.local is missing — the build will bake the"
  info "      default public origin. Create it before deploying (MIGRATION.md)."
fi

CURRENT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
info "repo sha       : ${CURRENT_SHA:0:12}"
info "build          : $BUILD_CMD"
info "web unit       : $WEB_UNIT      (systemd via: $SYSTEMCTL)"
info "worker unit    : $WORKER_UNIT"
info "health url     : $HEALTH_URL"
info "health marker  : $HEALTH_EXPECT   (timeout ${HEALTH_TIMEOUT}s)"

# Confirm the units exist (unless --check, where a missing unit is expected).
if [ "$CHECK_ONLY" -eq 0 ]; then
  for unit in "$WEB_UNIT" "$WORKER_UNIT"; do
    if ! $SYSTEMCTL cat "$unit" >/dev/null 2>&1; then
      oops "systemd unit '$unit' is not installed. Complete the owner setup in"
      oops "  deploy/MIGRATION.md (install the units) before deploying."
      exit 1
    fi
  done
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  say "check: verifying the units are installed"
  ok=1
  for unit in "$WEB_UNIT" "$WORKER_UNIT"; do
    if $SYSTEMCTL cat "$unit" >/dev/null 2>&1; then
      info "unit present : $unit"
    else
      info "unit MISSING : $unit  (install it per deploy/MIGRATION.md)"; ok=0
    fi
  done
  printf '\ndeployment --check: plan printed, NOTHING was changed.\n'
  [ "$ok" -eq 1 ] || { oops "one or more units are not installed yet."; exit 1; }
  exit 0
fi

# ---------------------------------------------------------------------------
say "2/6 build (snapshot .next, then $BUILD_CMD)"
# ---------------------------------------------------------------------------
# Move the live .next aside FIRST (a same-filesystem rename is instant and does
# NOT disturb the running server's already-open fds), so we build a complete,
# fresh .next before any restart — no chunk-mismatch under the running server
# (the hazard INSTALL.md warns about), and a clean rollback point.
rm -rf "$NEXT_ROLLBACK"
if [ -d "$NEXT_DIR" ]; then
  if ! mv -T "$NEXT_DIR" "$NEXT_ROLLBACK"; then
    oops "could not move $NEXT_DIR aside — aborting before any change."; exit 1
  fi
  info "snapshot: .next -> .next.rollback"
else
  info "no existing .next — first build (rollback will be unavailable)"
fi

if ! bash -c "$BUILD_CMD"; then
  oops "the build failed. Restoring the previous .next; nothing was restarted."
  rm -rf "$NEXT_DIR"
  [ -d "$NEXT_ROLLBACK" ] && mv -T "$NEXT_ROLLBACK" "$NEXT_DIR" || true
  exit 1
fi
info "build complete"

# ---------------------------------------------------------------------------
say "3/6 rollback point"
info "rollback target: $([ -d "$NEXT_ROLLBACK" ] && echo '.next.rollback (previous build)' || echo 'none (first build)')"

say "4/6 backup"
info "SKIPPED — a Next build is stateless (the Postgres DB is not touched here)."

# ---------------------------------------------------------------------------
say "5/6 apply — restart $WEB_UNIT onto the new build"
# ---------------------------------------------------------------------------
if ! $SYSTEMCTL restart "$WEB_UNIT"; then
  oops "restarting $WEB_UNIT failed."
  if rollback; then oops "rolled back to the previous build."; fi
  exit 1
fi
info "restarted $WEB_UNIT"

# ---------------------------------------------------------------------------
say "6/6 health, then restart $WORKER_UNIT"
# ---------------------------------------------------------------------------
if ! health_check; then
  oops "the new build is not healthy."
  if rollback; then oops "rolled back to the previous build."; fi
  exit 1
fi

# The worker has no HTTP surface; restart it to pick up new code, then confirm it
# came up. A worker failure does NOT roll back the healthy web build — the site
# stays up — but it IS a non-zero exit so the operator investigates.
if ! $SYSTEMCTL restart "$WORKER_UNIT"; then
  oops "the web app is healthy, but restarting $WORKER_UNIT FAILED."
  oops "  the site is up; the jobs worker is not. Investigate:"
  oops "  journalctl -u $WORKER_UNIT -n 50 --no-pager"
  exit 1
fi
if ! $SYSTEMCTL is-active --quiet "$WORKER_UNIT"; then
  oops "the web app is healthy, but $WORKER_UNIT is not active after restart."
  oops "  journalctl -u $WORKER_UNIT -n 50 --no-pager"
  exit 1
fi
info "restarted $WORKER_UNIT (active)"

# Success — drop the now-stale snapshot.
rm -rf "$NEXT_ROLLBACK"

printf '\ndeployment: brier %s is built, live on %s, and healthy; %s restarted.\n' \
  "${CURRENT_SHA:0:12}" "$WEB_UNIT" "$WORKER_UNIT"
