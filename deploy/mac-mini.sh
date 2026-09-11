#!/usr/bin/env bash
#
# Bring the Warmline API up on a machine at home, reachable at
# api.warmline.mziyo.com through a Cloudflare tunnel.
#
# No port forwarding and no public IP: cloudflared makes an outbound connection
# to Cloudflare, so nothing on the home router is opened. TLS terminates at
# Cloudflare. The API binds to 127.0.0.1, so the tunnel is the only way in and
# nothing else on the local network can reach it.
#
# Runs the service under launchd rather than Docker. Docker Desktop on macOS
# needs a logged-in GUI session, which is the wrong dependency for a machine
# that should come back on its own after a power cut. The Dockerfile in the
# repository root still works if you would rather use a container.
#
# Safe to run more than once.
#
#   bash deploy/mac-mini.sh
#
set -euo pipefail

CHECKOUT="${WARMLINE_DIR:-$HOME/warmline}"
TUNNEL="warmline"
# Single-level on purpose. Cloudflare's free Universal SSL covers mziyo.com and
# *.mziyo.com but not *.*.mziyo.com, so api.warmline.mziyo.com gets no
# certificate and fails the TLS handshake. Two levels deep needs paid Advanced
# Certificate Manager; renaming is free.
API_HOST="warmline-api.mziyo.com"
PAGE_ORIGIN="https://warmline.mziyo.com"
PORT="8000"
LABEL="com.mziyo.warmline"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"
TUNNEL_LABEL="com.mziyo.warmline-tunnel"
TUNNEL_PLIST="/Library/LaunchDaemons/${TUNNEL_LABEL}.plist"

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
die() { printf "\n\033[31mError: %s\033[0m\n" "$1" >&2; exit 1; }

# --- preflight -------------------------------------------------------------

say "Checking prerequisites"
command -v git >/dev/null || die "git is not installed."
command -v brew >/dev/null || die "Homebrew is not installed. See https://brew.sh"

# Take the first interpreter that is actually new enough, rather than assuming
# a name. A machine that has run a few projects tends to have several Pythons
# with none of them called python3.12.
PYTHON=""
for candidate in \
  python3.14 python3.13 python3.12 python3.11 python3 \
  /opt/homebrew/opt/python@3.14/bin/python3.14 \
  /opt/homebrew/opt/python@3.13/bin/python3.13 \
  /opt/homebrew/opt/python@3.12/bin/python3.12 \
  /opt/homebrew/opt/python@3.11/bin/python3.11
do
  path="$(command -v "$candidate" 2>/dev/null || true)"
  [ -n "$path" ] || continue
  if "$path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$path"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Interpreters found on PATH:"
  for candidate in python3 python3.11 python3.12 python3.13 python3.14; do
    path="$(command -v "$candidate" 2>/dev/null || true)"
    [ -n "$path" ] && echo "  $path -> $("$path" --version 2>&1)"
  done
  die "None of these is Python 3.11 or newer. Try: brew install python@3.12"
fi
echo "Using $PYTHON ($("$PYTHON" --version 2>&1))"

command -v cloudflared >/dev/null || { say "Installing cloudflared"; brew install cloudflared; }

# --- source ----------------------------------------------------------------

if [ -d "$CHECKOUT/.git" ]; then
  say "Updating $CHECKOUT"
  git -C "$CHECKOUT" pull --ff-only
else
  die "$CHECKOUT is not a checkout. Clone the repository there first."
fi

# --- the service -----------------------------------------------------------

say "Installing dependencies"
"$PYTHON" -m venv "$CHECKOUT/.venv"
"$CHECKOUT/.venv/bin/pip" install --quiet --upgrade pip
"$CHECKOUT/.venv/bin/pip" install --quiet -e "$CHECKOUT"

mkdir -p "$CHECKOUT/data" "$CHECKOUT/logs"

say "Writing the launchd daemon"
sudo tee "$PLIST" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>UserName</key><string>$(whoami)</string>
  <key>WorkingDirectory</key><string>${CHECKOUT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${CHECKOUT}/.venv/bin/uvicorn</string>
    <string>warmline.api.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>${PORT}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>WARMLINE_DB</key><string>${CHECKOUT}/data/warmline.sqlite3</string>
    <key>WARMLINE_ALLOWED_ORIGINS</key><string>${PAGE_ORIGIN}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${CHECKOUT}/logs/api.log</string>
  <key>StandardErrorPath</key><string>${CHECKOUT}/logs/api.err</string>
</dict>
</plist>
EOF

say "Starting the service"
# bootout is asynchronous. Firing bootstrap before the old job has finished
# unloading fails with "Bootstrap failed: 5: Input/output error", so wait for
# it to actually go away first.
sudo launchctl bootout "system/${LABEL}" 2>/dev/null || true
for _ in $(seq 1 20); do
  sudo launchctl print "system/${LABEL}" >/dev/null 2>&1 || break
  sleep 0.5
done

# Neither of these is fatal on its own: the service may already be loaded, in
# which case kickstart is enough. Whether it actually came up is decided by the
# health check below, not by these exit codes.
sudo launchctl bootstrap system "$PLIST" 2>/dev/null || true
sudo launchctl kickstart -k "system/${LABEL}" 2>/dev/null || true

say "Waiting for the API"
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null \
  || die "The API did not come up. Try: tail -50 ${CHECKOUT}/logs/api.err"
echo "API is up on 127.0.0.1:${PORT}"

# --- the tunnel ------------------------------------------------------------

if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
  say "Authorising cloudflared (a browser window will open)"
  cloudflared tunnel login
else
  echo "Using the existing cloudflared certificate."
  echo "If it was issued for a different domain than ${API_HOST}, run"
  echo "'cloudflared tunnel login' again and pick the right zone."
fi

if ! cloudflared tunnel list 2>/dev/null | grep -qE "[[:space:]]${TUNNEL}[[:space:]]"; then
  say "Creating the tunnel"
  cloudflared tunnel create "$TUNNEL"
fi

TUNNEL_ID="$(cloudflared tunnel list --output json | "$PYTHON" -c \
  "import json,sys; print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='${TUNNEL}'))")"

say "Writing the tunnel config"
mkdir -p "$HOME/.cloudflared"
cat > "$HOME/.cloudflared/config.yml" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${HOME}/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: ${API_HOST}
    service: http://127.0.0.1:${PORT}
  - service: http_status:404
EOF

say "Pointing ${API_HOST} at the tunnel"
# cloudflared picks the zone from ~/.cloudflared/cert.pem. If that cert was
# issued for a different domain, it does not fail — it quietly creates
# "api.warmline.mziyo.com.someotherdomain.com" and reports success. So check
# what it actually made rather than trusting the exit code.
ROUTE_OUTPUT="$(cloudflared tunnel route dns "$TUNNEL" "$API_HOST" 2>&1 || true)"
echo "$ROUTE_OUTPUT"

# Match the hostname as a whole word. The wrong-zone case appends another
# domain, so the giveaway is a dot straight after the hostname rather than
# whitespace. Dots in the hostname are escaped so they cannot match anything.
HOST_RE="$(printf '%s' "$API_HOST" | sed 's/\./\\./g')"

if echo "$ROUTE_OUTPUT" | grep -q "already exists"; then
  echo "(DNS record already exists — carrying on)"
elif echo "$ROUTE_OUTPUT" | grep -qE "Added CNAME ${HOST_RE}([[:space:]]|$)"; then
  echo "DNS record created correctly."
elif echo "$ROUTE_OUTPUT" | grep -q "Added CNAME"; then
  cat <<EOF

The DNS record was created in the wrong zone. cloudflared took the zone from
\$HOME/.cloudflared/cert.pem, which belongs to a different domain, and appended
${API_HOST} to it as a subdomain.

  1. cloudflared tunnel login          # choose the zone for ${API_HOST}
  2. cloudflared tunnel route dns ${TUNNEL} ${API_HOST}
  3. Delete the wrong record in the Cloudflare dashboard.

EOF
  die "Wrong DNS zone — see above."
fi

say "Installing the tunnel as its own service"
# Deliberately NOT `cloudflared service install`. That installs a single
# daemon called com.cloudflare.cloudflared, and on a machine already running
# another tunnel it silently does nothing: the existing service keeps serving
# the other tunnel, this one gets no connections, and every request returns
# Cloudflare error 1033 while the logs cheerfully report a healthy tunnel.
#
# So this tunnel gets its own labelled daemon and leaves any existing one alone.
CLOUDFLARED_BIN="$(command -v cloudflared)"
sudo tee "$TUNNEL_PLIST" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${TUNNEL_LABEL}</string>
  <key>UserName</key><string>$(whoami)</string>
  <key>ProgramArguments</key>
  <array>
    <string>${CLOUDFLARED_BIN}</string>
    <string>--no-autoupdate</string>
    <string>--config</string><string>${HOME}/.cloudflared/config.yml</string>
    <string>tunnel</string><string>run</string><string>${TUNNEL}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${CHECKOUT}/logs/tunnel.log</string>
  <key>StandardErrorPath</key><string>${CHECKOUT}/logs/tunnel.err</string>
</dict>
</plist>
EOF

sudo launchctl bootout "system/${TUNNEL_LABEL}" 2>/dev/null || true
for _ in $(seq 1 20); do
  sudo launchctl print "system/${TUNNEL_LABEL}" >/dev/null 2>&1 || break
  sleep 0.5
done
sudo launchctl bootstrap system "$TUNNEL_PLIST" 2>/dev/null || true
sudo launchctl kickstart -k "system/${TUNNEL_LABEL}" 2>/dev/null || true

say "Waiting for the tunnel to register"
for _ in $(seq 1 30); do
  if cloudflared tunnel info "$TUNNEL" 2>/dev/null | grep -qi "connector\|CONNECTOR ID\|ams\|lhr\|iad"; then break; fi
  sleep 2
done
cloudflared tunnel info "$TUNNEL" 2>/dev/null | head -6 || true

# --- keep the machine awake ------------------------------------------------

say "Disabling sleep (the link dies if this machine naps)"
sudo pmset -a sleep 0 disksleep 0 || echo "(could not change power settings — do it in System Settings)"

say "Done"
cat <<EOF

  API (local):  http://127.0.0.1:${PORT}/healthz
  API (public): https://${API_HOST}/healthz

Give DNS a minute, then check the public URL.

  Update:   bash ${CHECKOUT}/deploy/mac-mini.sh
  Logs:     tail -f ${CHECKOUT}/logs/api.err
  Tunnel:   tail -f ${CHECKOUT}/logs/tunnel.err
  Stop:     sudo launchctl bootout system/${LABEL} && sudo launchctl bootout system/${TUNNEL_LABEL}

EOF
