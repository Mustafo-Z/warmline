# Deployment

The demo is hosted in two parts.

- **The page** is on Vercel at `warmline.mziyo.com`, built from `web/`, with
  `NEXT_PUBLIC_API_BASE` pointing at the API.
- **The API** runs on a Mac mini at home, reachable at `warmline-api.mziyo.com`
  through a Cloudflare tunnel.

`mac-mini.sh` sets up the API. It installs the package into a virtual
environment, runs uvicorn under launchd bound to `127.0.0.1`, creates a
Cloudflare tunnel to it, points the DNS record at the tunnel, and runs the
tunnel as its own launchd service so it doesn't interfere with other tunnels on
the machine.

It uses launchd instead of Docker because Docker Desktop on macOS needs someone
logged in, and a LaunchDaemon starts at boot. The `Dockerfile` in the repository
root still works if you'd rather run a container.

No ports are opened on the router. `cloudflared` connects out to Cloudflare, and
the API only listens on localhost, so nothing else on the network can reach it.

The database is in `data/` inside the checkout, so it survives restarts. The app
only seeds when there are no prospects, so redeploying doesn't wipe it.

## Live voice

1. Put `ELEVENLABS_API_KEY` and `WARMLINE_VOICE_PASSCODE` in `.env` in the
   checkout on the serving machine. The script sets it to `chmod 600`, and the
   key never reaches the browser.
2. Run `.venv/bin/python -m warmline.voice.sync_agent`. It creates the
   ElevenLabs agent from the files in `agent/` and writes the agent id into
   `.env`. Run it again after changing the prompt, the voice or the model.
3. Re-run `mac-mini.sh` so the API picks up the settings.

Sessions are capped per hour, and each one is limited to the call length in
`agent/agent_config.json`. To see where the time went in a slow conversation,
run `.venv/bin/python -m warmline.voice.timing <conversation_id>` on the same
machine.
