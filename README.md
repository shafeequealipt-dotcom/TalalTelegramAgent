# Talal Homeo Telegram Agent

A Telegram-controlled agent that writes and auto-publishes daily blog posts for
[Dr. Talal's Alsharaf Homoeo Medical Centre](https://drtalalhomeo.in) (Kochi,
Kerala). Patterned after the DNH Care blog agent, adapted for a different site
architecture: this agent's code lives in **this** repo, and it publishes into a
**separate, already-existing** website repo
([TalalHomeo](https://github.com/shafeequealipt-dotcom/TalalHomeo), an Astro
site) by writing a markdown file and pushing straight to its `main` branch.

## How it works

```
Telegram /generate, or the daily scheduled job
        │
        ▼
bot/content.py   — asks the current Cloudflare Workers AI model for structured
        │           JSON (title, description, tags, sections, FAQs), then
        │           deterministically renders Astro frontmatter + markdown
        ▼           so the site's content schema always validates
bot/check_post.py — safety/quality gate: banned overclaim words, banned
        │           medical-advice phrases (never "stop your medication" /
        │           "skip the surgery"), banned remedy names, word count,
        │           frontmatter shape — mirrors src/content.config.ts and
        │           BLOG-AGENT-SPEC.md in the site repo
        ▼
bot/publisher.py — on pass: commits the .md file straight into the site
                    repo's src/content/blog/ and pushes to main. The site's
                    own GitHub Actions workflow builds it (Astro validates
                    frontmatter again at build time), rewrites its blog
                    index + sitemap.xml, and deploys — no manual approval
                    step, no manual index/sitemap editing needed here.
```

No Google Business Profile integration in this version (kept out deliberately
to keep the agent simple — see the DNH Care original if you want to port it
back in later).

## Telegram commands

- `/generate` – write and auto-publish a post right now
- `/topics` – show the topic queue
- `/addtopic <topic>` – add a topic to the queue
- `/model`, `/models`, `/setmodel <n>` – see/switch the Cloudflare Workers AI model
- `/time`, `/settime HH:MM-HH:MM` – see/set the daily post window (IST)
- `/prompt`, `/setprompt <text>` – see/edit the content-generation prompt

## Repo layout

| Path | What |
|---|---|
| `bot/bot.py` | Telegram app, commands, daily scheduling + watchdog |
| `bot/config.py` | Env vars, brand facts, category → service-page map, runtime state |
| `bot/content.py` | LLM call + deterministic markdown/frontmatter rendering |
| `bot/llm.py` | Cloudflare Workers AI client |
| `bot/topics.py` | Topic queue (`topics.md`) + trending-topic auto-pick |
| `bot/check_post.py` | Safety/quality gate — run before every publish |
| `bot/publisher.py` | Git operations against the site repo (and, for `/setprompt`, this repo) |
| `content_prompt.txt` | The live, editable content-generation prompt |
| `topics.md` | The topic queue + done log |

## Setup

See [SETUP.md](SETUP.md) for the full walkthrough (env vars, first run, systemd).

Quick local test:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp bot/.env.example bot/.env   # fill in real values, or export as shell env vars
git clone https://github.com/shafeequealipt-dotcom/TalalHomeo.git /path/to/TalalHomeo
export REPO_DIR=/path/to/TalalHomeo
python -m bot.bot
```

Then in Telegram: `/start`, then `/generate` to test one post end-to-end.
