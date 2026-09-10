#!/usr/bin/env bash
#
# Bring the Warmline API up on a machine at home, reachable at
# api.warmline.mziyo.com through a Cloudflare tunnel.
#
# No port forwarding and no public IP: cloudflared makes an outbound connection
# to Cloudflare, so nothing on the home router is opened. TLS terminates at
# Cloudflare.
#
# Safe to run more than once.
#
#   bash deploy/mac-mini.sh
#
set -euo pipefail

REPO="Mustafo-Z/warmline"
CHECKOUT="${WARMLINE_DIR:-$HOME/warmline}"
TUNNEL="warmline"
API_HOST="api.warmline.mziyo.com"
PAGE_ORIGIN="https://warmline.mziyo.com"
PORT="8000"

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
die() { printf "\n\033[31mError: %s\033[0m\n" "$1" >&2; exit 1; }

# --- preflight -------------------------------------------------------------

say "Checking prerequisites"
command -v docker >/dev/null || die "Docker is not installed. Install Docker Desktop and start it."
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop."
command -v git >/dev/null || die "git is not installed."

if ! command -v cloudflared >/dev/null; then
  command -v brew >/dev/null || die "cloudflared is missing and Homebrew is not installed."
  say "Installing cloudflared"
  brew install cloudflared
fi

if ! command -v gh >/dev/null; then
  command -v brew >/dev/null || die "gh is missing and Homebrew is not installed."
  brew install gh
fi
gh auth status >/dev/null 2>&1 || die "Run 'gh auth login' first — the repository is private."

# --- source ----------------------------------------------------------------

if [ -d "$CHECKOUT/.git" ]; then
  say "Updating $CHECKOUT"
  git -C "$CHECKOUT" pull --ff-only
else
  say "Cloning into $CHECKOUT"
  gh repo clone "$REPO" "$CHECKOUT"
fi

# --- the API ---------------------------------------------------------------

say "Building the image"
docker build -t warmline-api "$CHECKOUT"

say "Starting the container"
docker rm -f warmline-api >/dev/null 2>&1 || true
docker volume create warmline-data >/dev/null
docker run -d \
  --name warmline-api \
  --restart unless-stopped \
  -p "127.0.0.1:${PORT}:8000" \
  -e PORT=8000 \
  -e WARMLINE_DB=/data/warmline.sqlite3 \
  -e "WARMLINE_ALLOWED_ORIGINS=${PAGE_ORIGIN}" \
  -v warmline-data:/data \
  warmline-api >/dev/null

# Bound to 127.0.0.1 on purpose: the only way in is the tunnel, so the API is
# not reachable from anything else on the home network.

say "Waiting for the API"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null || die "The API did not come up. Try: docker logs warmline-api"
echo "API is up on 127.0.0.1:${PORT}"

# --- the tunnel ------------------------------------------------------------

if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
  say "Authorising cloudflared (a browser window will open)"
  cloudflared tunnel login
fi

if ! cloudflared tunnel list 2>/dev/null | grep -q "\b${TUNNEL}\b"; then
  say "Creating the tunnel"
  cloudflared tunnel create "$TUNNEL"
fi

TUNNEL_ID="$(cloudflared tunnel list --output json | python3 -c \
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
cloudflared tunnel route dns "$TUNNEL" "$API_HOST" || \
  echo "(DNS record already exists — carrying on)"

say "Installing cloudflared as a service so it survives a reboot"
sudo cloudflared service install 2>/dev/null || sudo launchctl kickstart -k system/com.cloudflare.cloudflared || true

# --- keep the machine awake ------------------------------------------------

say "Disabling sleep (the link dies if this machine naps)"
sudo pmset -a sleep 0 disksleep 0 || echo "(could not change power settings — do it in System Settings)"

say "Done"
cat <<EOF

  API (local):  http://127.0.0.1:${PORT}/healthz
  API (public): https://${API_HOST}/healthz

Give DNS a minute, then check the public URL. If it 502s, the tunnel is up but
the container is not: docker logs warmline-api

To update later:  bash deploy/mac-mini.sh
To stop:          docker rm -f warmline-api && sudo cloudflared service uninstall

EOF
