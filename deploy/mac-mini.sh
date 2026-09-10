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
API_HOST="api.warmline.mziyo.com"
PAGE_ORIGIN="https://warmline.mziyo.com"
PORT="8000"
LABEL="com.mziyo.warmline"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
die() { printf "\n\033[31mError: %s\033[0m\n" "$1" >&2; exit 1; }

# --- preflight -------------------------------------------------------------

say "Checking prerequisites"
command -v git >/dev/null || die "git is not installed."
command -v brew >/dev/null || die "Homebrew is not installed. See https://brew.sh"

PYTHON="$(command -v python3.12 || command -v python3 || true)"
[ -n "$PYTHON" ] || die "No python3 found. Try: brew install python@3.12"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11 or newer is required. Try: brew install python@3.12"

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
sudo launchctl bootout "system/${LABEL}" 2>/dev/null || true
sudo launchctl bootstrap system "$PLIST"
sudo launchctl kickstart -k "system/${LABEL}"

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
cloudflared tunnel route dns "$TUNNEL" "$API_HOST" \
  || echo "(DNS record already exists — carrying on)"

say "Installing cloudflared as a service"
sudo cloudflared service install 2>/dev/null \
  || sudo launchctl kickstart -k system/com.cloudflare.cloudflared \
  || true

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
  Stop:     sudo launchctl bootout system/${LABEL}

EOF
