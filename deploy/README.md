# Deployment

The demo is hosted in two halves.

- **The page** is on Vercel at `warmline.mziyo.com`, built from `web/`, with
  `NEXT_PUBLIC_API_BASE` pointing at the API.
- **The API** runs in Docker on a machine at home, reachable at
  `api.warmline.mziyo.com` through a Cloudflare tunnel.

`mac-mini.sh` sets up the second half. It installs the package into a virtual
environment, runs uvicorn under launchd bound to `127.0.0.1` only, opens a
Cloudflare tunnel to it, points the DNS record at the tunnel and installs
cloudflared as a service.

It uses launchd rather than Docker on purpose. Docker Desktop on macOS needs a
logged-in GUI session, which is the wrong dependency for a machine that should
come back on its own after a power cut; a LaunchDaemon starts at boot with
nobody logged in. The `Dockerfile` in the repository root still works for
anyone who would rather run a container.

Nothing on the home router is opened. `cloudflared` makes an outbound
connection to Cloudflare, so there is no port forward and no public IP
involved, and the container is not reachable from anything else on the local
network either.

The database sits in `data/` inside the checkout, so state survives restarts. The
application seeds only when there are no prospects, so a redeploy never
overwrites what someone has been clicking on.
