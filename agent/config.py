"""Central config — Cloudflare Workers AI for content generation, runtime-
switchable model persisted in state.json.

This agent lives in its OWN repo. It writes into a SEPARATE, dedicated clone of
the website repo checked out at REPO_DIR, and pushes to that repo's `main`
branch to publish. Its own repo (this one) only ever holds the agent's code +
operational files (content_prompt.txt, topics.md) — those are NOT pushed
automatically at runtime, except content_prompt.txt via `agent.cli set-prompt`,
which commits to THIS repo.

No Telegram, no persistent process: a systemd timer on the server runs
`python -m agent.run_daily` once a day (see agent/deploy/), and
RandomizedDelaySec on that timer reproduces the "randomized time within a
window" behaviour the DNHCare original did in-process.
"""
import os
import json
from dotenv import load_dotenv

# Load agent/.env (does NOT override real system env vars).
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _env(*names, default=None, required=False):
    """Return the first env var found among `names` (case-insensitive on Windows,
    exact on Linux — so we list common casings)."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    if required:
        raise RuntimeError(f"Missing required env var (any of): {', '.join(names)}")
    return default


# ---- Cloudflare Workers AI (OpenAI-compatible) for content generation ----
CF_API_TOKEN = _env("TALAL_CloudFlare_API", "CLOUDFLARE_API_TOKEN", required=True)
CF_ACCOUNT_ID = _env("TALAL_CloudFlare_AccountID", "CLOUDFLARE_ACCOUNT_ID", required=True)
CF_BASE_URL = _env("CF_BASE_URL",
                   default=f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/v1")

# Fallback list used if the live roster fetch fails, or by `agent.cli models`.
PRESET_MODELS = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/openai/gpt-oss-120b",
    "@cf/openai/gpt-oss-20b",
    "@cf/meta/llama-4-scout-17b-16e-instruct",
    "@cf/qwen/qwen2.5-coder-32b-instruct",
    "@cf/qwen/qwq-32b",
    "@cf/mistralai/mistral-small-3.1-24b-instruct",
]
DEFAULT_MODEL = _env("DEFAULT_MODEL", default=PRESET_MODELS[0])

# ---- Website repo (publish target) — a DEDICATED clone, not the user's own
#      working checkout, and not this repo ----
GITHUB_TOKEN = _env("TALAL_GitHub_Token", "TALAL_GITHUB_TOKEN", "GITHUB_TOKEN", required=True)
GITHUB_REPO = _env("SITE_GITHUB_REPO", default="shafeequealipt-dotcom/TalalHomeo")
REPO_DIR = _env("REPO_DIR", required=True)  # dedicated local clone of the site repo
PUBLISH_BRANCH = _env("PUBLISH_BRANCH", default="main")

BLOG_DIR = os.path.join(REPO_DIR, "src", "content", "blog")
SITE_URL = _env("SITE_URL", default="https://drtalalhomeo.in")

# ---- This agent's OWN repo (for `agent.cli set-prompt` — commits
#      content_prompt.txt here, NOT to the site repo). Defaults to wherever
#      this code is actually checked out. ----
AGENT_REPO_DIR = _env("AGENT_REPO_DIR",
                      default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT_GITHUB_REPO = _env("AGENT_GITHUB_REPO",
                         default="shafeequealipt-dotcom/TalalTelegramAgent")
# Falls back to GITHUB_TOKEN if you don't need a separate token for this repo.
AGENT_GITHUB_TOKEN = _env("AGENT_GitHub_Token", "AGENT_GITHUB_TOKEN", default=GITHUB_TOKEN)

TOPICS_FILE = os.path.join(AGENT_REPO_DIR, "topics.md")
PROMPT_FILE = os.path.join(AGENT_REPO_DIR, "content_prompt.txt")
CHECK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_post.py")
# Runtime state lives beside the code (gitignored) so a reset of REPO_DIR never wipes it.
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Brand facts (kept in sync with src/data/clinic.json in the site repo)
CLINIC_NAME = "Dr. Talal's Alsharaf Homoeo Medical Centre"
PHONE = "+91 89217 11721"
WA = "https://wa.me/918921711721"
ADDRESS_LINE = "Near Bharat Petroleum Pump, Kappalandimukku, Kochi, Kerala 682002"

# category key -> (service slug under /services/<slug>, human label) — mirrors
# src/data/clinic.json "services" in the site repo. Keep these two in sync by hand
# if services are ever added/renamed there.
CATEGORY_SERVICE = {
    "Allergy": ("allergy-sinusitis", "Allergy & Sinusitis"),
    "Pediatric": ("pediatric-care", "Pediatric Care & Adenoids"),
    "Migraine": ("migraine-headaches", "Migraine & Headaches"),
    "Skin": ("skin-hair", "Skin & Hair"),
    "General": ("general-lifestyle", "General & Lifestyle"),
}
CATEGORIES = list(CATEGORY_SERVICE.keys())


# ---- runtime model state (switchable via `agent.cli set-model`) ----
def _read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def get_model() -> str:
    return _read_state().get("model", DEFAULT_MODEL)


def set_model(model_id: str):
    state = _read_state()
    state["model"] = model_id.strip()
    _write_state(state)
    return state["model"]
