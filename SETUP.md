# Setup

## 1. Credentials you need

| Credential | Where to get it | Env var |
|---|---|---|
| Telegram bot token | Message [@BotFather](https://t.me/BotFather) → `/newbot` | `TALAL_Telegram_Token` |
| Your Telegram chat id | Message [@userinfobot](https://t.me/userinfobot) | `TALAL_Telegram_ID` |
| Cloudflare account ID | Cloudflare dashboard → right sidebar | `TALAL_CloudFlare_AccountID` |
| Cloudflare API token | Cloudflare dashboard → My Profile → API Tokens → create a token with **Workers AI: Edit** | `TALAL_CloudFlare_API` |
| GitHub PAT (site repo) | github.com → Settings → Developer settings → Fine-grained tokens → **Contents: Read and write** on `shafeequealipt-dotcom/TalalHomeo` | `TALAL_GitHub_Token` |

Per this project's global rule: **put every one of these in `~/.zshrc`** as
`export NAME="..."` lines on whichever machine runs the bot — never in a
committed file. `bot/.env` is only a fallback for a value you genuinely can't
put in the shell profile (e.g. on a server where you don't control the login
shell) — see `bot/.env.example`.

If your GitHub PAT's scope also covers this agent's own repo
(`TalalTelegramAgent`), you don't need a second token — `/setprompt` reuses
`TALAL_GitHub_Token` by default. Otherwise set `AGENT_GitHub_Token` separately.

## 2. Clone the site repo the agent will publish into

The agent needs its own local working clone of the **website** repo (separate
from this agent repo) to commit posts into:

```bash
git clone https://github.com/shafeequealipt-dotcom/TalalHomeo.git /opt/talal-agent/TalalHomeo
export REPO_DIR=/opt/talal-agent/TalalHomeo
```

## 3. Install and run

```bash
cd TalalTelegramAgent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.bot
```

On first run it schedules tomorrow's (or today's, if the window hasn't passed)
auto-post and starts polling Telegram. Message the bot `/start`, then
`/generate` to test the full pipeline once before trusting the daily schedule.

## 4. Running it as a systemd service (Linux server)

A template unit is at `bot/deploy/talal-bot.service`. Adjust the paths, then:

```bash
sudo cp bot/deploy/talal-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now talal-bot
sudo journalctl -u talal-bot -f    # tail logs
```

Make sure the service's user has the env vars above in its shell profile, or
fill in `bot/.env` next to `bot/bot.py`.

## 5. Verify the site repo's own CI is wired up

This agent pushes to `TalalHomeo`'s `main` branch; that repo's own
`.github/workflows/deploy.yml` needs its 4 repository secrets
(`SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `DEPLOY_PATH`) configured for the
push to actually deploy to the live site — see that repo's `DEPLOY.md` if
they aren't set yet. Until they are, posts land on GitHub but won't reach
https://drtalalhomeo.in automatically.
