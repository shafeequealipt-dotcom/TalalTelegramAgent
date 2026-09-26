"""Shared Cloudflare Workers AI (OpenAI-compatible) client with a rate-limit
retry — models can be rate-limited upstream on the free tier, so retry a few
times before giving up."""
import time
import json
import urllib.request
import openai
from openai import OpenAI
from . import config

# Cloudflare's catalog spans many task types (speech, image, embeddings, etc.)
# under one /ai/models/search endpoint; only "Text Generation" models can take a
# chat-completions blog-writing prompt. Models tagged moderation/guardrails
# (e.g. llama-guard) are classifiers, not general writers — excluded too.
_TEXT_GEN_TASK = "Text Generation"
_EXCLUDE_TAGS = ("moderation", "guardrails")
_MODELS_SEARCH_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}"
    "/ai/models/search")


def list_models() -> list:
    """Fetch the CURRENT Text Generation model roster live from Cloudflare,
    sorted alphabetically. Stdlib-only GET so it can't be tripped up by SDK
    quirks. Raises on network/HTTP error — caller falls back to
    config.PRESET_MODELS.

    NOTE: the endpoint's page/per_page params don't behave as documented (page=2
    can return 0 results regardless of total_count) — a single unparameterized
    call returns the full accessible result set; don't build pagination-following
    logic around total_count without verifying it first."""
    req = urllib.request.Request(
        _MODELS_SEARCH_URL,
        headers={"Authorization": f"Bearer {config.CF_API_TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r).get("result", [])
    ids = []
    for m in data:
        if m.get("task", {}).get("name") != _TEXT_GEN_TASK:
            continue
        if any(t in _EXCLUDE_TAGS for t in m.get("tags", [])):
            continue
        name = str(m.get("name", ""))
        if name:
            ids.append(name)
    return sorted(ids)

# max_retries=0 so the SDK does NOT add its own (long, Retry-After-honoring) backoff on
# top of ours — otherwise a throttled model hangs for minutes. We handle 429 here.
_client = OpenAI(
    base_url=config.CF_BASE_URL,
    api_key=config.CF_API_TOKEN,
    max_retries=0,
    timeout=300,   # 5 min per call — large models can be slow under load
)


def chat(messages, model=None, retries=2, wait_cap=12, **kw):
    """Chat completion against the current (or given) model. On 429 we retry a couple
    of times with a short, capped wait, then fail fast so the user can switch models."""
    model = model or config.get_model()
    last = None
    for attempt in range(retries + 1):
        try:
            return _client.chat.completions.create(model=model, messages=messages, **kw)
        except openai.RateLimitError as e:
            last = e
            if attempt == retries:
                break
            wait = 4
            try:
                wait = int(e.response.headers.get("retry-after", "4"))
            except Exception:  # noqa
                pass
            time.sleep(min(wait, wait_cap))
    raise last
