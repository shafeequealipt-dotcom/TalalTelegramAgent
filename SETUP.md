# Setup

## 1. Credentials you need

| Credential | Where to get it | Env var |
|---|---|---|
| Cloudflare account ID | Cloudflare dashboard → right sidebar | `TALAL_CloudFlare_AccountID` |
| Cloudflare API token | Cloudflare dashboard → My Profile → API Tokens → create a token with **Workers AI: Edit** | `TALAL_CloudFlare_API` |
| GitHub PAT (site repo) | github.com → Settings → Developer settings → Fine-grained tokens → **Contents: Read and write** on `shafeequealipt-dotcom/TalalHomeo` | `TALAL_GitHub_Token` |

Per this project's global rule: **put every one of these in the server's shell
profile** (e.g. `~/.bashrc` for the `ubuntu` user, or a systemd
`EnvironmentFile` that isn't committed) — never in a file checked into git.
`agent/.env` is only a fallback — see `agent/.env.example`.

If your GitHub PAT's scope also covers this agent's own repo
(`TalalTelegramAgent`), you don't need a second token — `agent.cli set-prompt`
reuses `TALAL_GitHub_Token` by default. Otherwise set `AGENT_GitHub_Token`
separately.

## 2. Clone a DEDICATED copy of the site repo

The agent needs its **own** local clone of the website repo — never your
personal working checkout — because it runs `git reset --hard` on every run
to guarantee a clean, fast-forward publish, which would wipe uncommitted
manual edits:

```bash
git clone https://github.com/shafeequealipt-dotcom/TalalHomeo.git /opt/talal-agent/TalalHomeo
export REPO_DIR=/opt/talal-agent/TalalHomeo
```

## 3. Install this agent on the Oracle server

```bash
sudo mkdir -p /opt/talal-agent && sudo chown ubuntu:ubuntu /opt/talal-agent
cd /opt/talal-agent
git clone https://github.com/shafeequealipt-dotcom/TalalTelegramAgent.git
cd TalalTelegramAgent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Test the full pipeline once manually before trusting the daily timer:

```bash
python -m agent.run_daily
```

## 4. Run it daily via systemd timer (no persistent process)

Templates are at `agent/deploy/talal-agent.service` and `.timer`. Adjust the
paths inside them if you didn't use `/opt/talal-agent`, then:

```bash
sudo cp agent/deploy/talal-agent.service agent/deploy/talal-agent.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now talal-agent.timer
systemctl list-timers talal-agent.timer     # confirm the next scheduled run
journalctl -u talal-agent -f                # tail logs from the last/next run
```

The timer fires once a day inside a randomized window (06:00–09:00 IST by
default — edit `OnCalendar`/`RandomizedDelaySec` in the `.timer` file to
change it) and runs the service exactly once. `Persistent=true` means a missed
run (server was off) fires once at the next boot instead of silently skipping
the day.

Make sure the `ubuntu` user's shell profile has the env vars from step 1, or
fill in `agent/.env` next to `agent/config.py`.

## 5. Verify the site repo's own CI is wired up

This agent pushes to `TalalHomeo`'s `main` branch; that repo's own
`.github/workflows/deploy.yml` needs its 4 repository secrets
(`SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `DEPLOY_PATH`) configured for the
push to actually deploy to the live site — see that repo's `DEPLOY.md` if
they aren't set yet. Until they are, posts land on GitHub but won't reach
https://drtalalhomeo.in automatically.
