# Talal Homeo Content Agent

A daily content agent that writes and auto-publishes blog posts for
[Dr. Talal's Alsharaf Homoeo Medical Centre](https://drtalalhomeo.in) (Kochi,
Kerala). Runs once a day as a systemd-timed job on the Oracle server — no
Telegram, no persistent process, no manual approval step.

This agent's code lives in **this** repo. It publishes into a **separate,
dedicated clone** of the website repo
([TalalHomeo](https://github.com/shafeequealipt-dotcom/TalalHomeo), an Astro
site) by writing a markdown file and pushing straight to its `main` branch —
never into anyone's personal working checkout of that repo.

## How it works

```
systemd timer fires once a day, at a randomized minute within a window
        │
        ▼
agent/run_daily.py — takes the next queued topic (topics.md), or auto-picks
        │              a timely one via the current Cloudflare Workers AI
        │              model if the queue is empty
        ▼
agent/content.py   — asks the model for structured JSON (title, description,
        │             tags, sections, FAQs), then deterministically renders
        ▼             Astro frontmatter + markdown so the site's schema always validates
agent/check_post.py — safety/quality gate: banned overclaim words, banned
        │             medical-advice phrases (never "stop your medication" /
        │             "skip the surgery"), banned remedy names, word count,
        │             frontmatter shape — mirrors src/content.config.ts and
        │             BLOG-AGENT-SPEC.md in the site repo
        ▼
agent/publisher.py — on pass: commits the .md file into the site repo's
                      src/content/blog/ and pushes to main. The site's own
                      GitHub Actions workflow builds it (Astro validates
                      frontmatter again at build time), rewrites its blog
                      index + sitemap.xml, and deploys.
```

A failed draft (gate failure twice, or every auto-picked topic colliding with
an existing post) simply exits non-zero and leaves the topic queued — logged
via `journalctl`, picked up again on the next scheduled run or a manual
`python -m agent.cli generate`.

No Google Business Profile integration in this version — that's the next
phase (see the DNH Care original this agent is patterned after if you want a
reference for the GBP local-post flow).

## Location-based content

`topics.md` currently prioritizes one genuinely-local post per area in
`clinic.json`'s `areasServed` (Kappalandimukku, Palluruthy, Thoppumpady,
Ernakulam, plus a Kochi-wide angle) — each grounded in a real feature of that
place (traffic/dust near a junction, backwater/fishing-community skin
exposure, port air quality, office-commute stress, hard water), not the same
template with a town name swapped. See `topics.md` for the current queue.

## Manual control (in place of the old Telegram commands)

Run these over SSH on the server (or locally, with `REPO_DIR` pointed at a
throwaway clone):

```bash
python -m agent.cli generate                        # write + publish one post now
python -m agent.cli generate --topic "[Skin] ..."    # force a specific topic
python -m agent.cli topics                           # show the queue
python -m agent.cli add-topic "[Allergy] ..."        # queue a topic
python -m agent.cli models                           # list current Cloudflare models
python -m agent.cli set-model <id-or-number>          # switch the writing model
python -m agent.cli prompt                            # show the content prompt
python -m agent.cli set-prompt path/to/file.txt       # update + commit the prompt
```

## Repo layout

| Path | What |
|---|---|
| `agent/run_daily.py` | The scheduled entrypoint — one run, one post, exits |
| `agent/cli.py` | Manual commands (generate/topics/models/prompt) |
| `agent/config.py` | Env vars, brand facts, category → service-page map, runtime state |
| `agent/content.py` | LLM call + deterministic markdown/frontmatter rendering |
| `agent/llm.py` | Cloudflare Workers AI client |
| `agent/topics.py` | Topic queue (`topics.md`) + trending-topic auto-pick |
| `agent/check_post.py` | Safety/quality gate — run before every publish |
| `agent/publisher.py` | Git operations against the site repo (and, for `set-prompt`, this repo) |
| `agent/deploy/talal-agent.service` + `.timer` | systemd units for the daily run |
| `content_prompt.txt` | The live, editable content-generation prompt |
| `topics.md` | The topic queue + done log |

## Setup

See [SETUP.md](SETUP.md) for the full walkthrough (credentials, the dedicated
site clone, systemd timer).

Quick local test:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp agent/.env.example agent/.env   # fill in real values, or export as shell env vars
git clone https://github.com/shafeequealipt-dotcom/TalalHomeo.git /path/to/TalalHomeo-agent-clone
export REPO_DIR=/path/to/TalalHomeo-agent-clone
python -m agent.run_daily
```
