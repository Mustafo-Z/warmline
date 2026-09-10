# Deployment

The demo is hosted in two halves.

- **The page** is on Vercel at `warmline.mziyo.com`, built from `web/`, with
  `NEXT_PUBLIC_API_BASE` pointing at the API.
- **The API** runs in Docker on a machine at home, reachable at
  `api.warmline.mziyo.com` through a Cloudflare tunnel.

`mac-mini.sh` sets up the second half. It builds the image, runs the container
bound to `127.0.0.1` only, opens a Cloudflare tunnel to it, points the DNS
record at the tunnel and installs cloudflared as a service so it survives a
reboot.

Nothing on the home router is opened. `cloudflared` makes an outbound
connection to Cloudflare, so there is no port forward and no public IP
involved, and the container is not reachable from anything else on the local
network either.

The database sits on a Docker volume, so state survives restarts. The
application seeds only when there are no prospects, so a redeploy never
overwrites what someone has been clicking on.
