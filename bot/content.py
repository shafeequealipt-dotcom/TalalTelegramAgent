"""Generate a blog post: a Cloudflare Workers AI model produces structured JSON
content, Python assembles the markdown + frontmatter deterministically so the
site's content-collection schema (src/content.config.ts in the TalalHomeo repo)
always validates — title/description length, tag count and date shape are
clamped/repaired in code rather than trusted from the model."""
import re
import json
import datetime
from typing import List
import openai
from pydantic import BaseModel, Field, ValidationError
from . import config, llm


class Section(BaseModel):
    heading: str
    paragraphs: List[str] = Field(default_factory=list)
    bullets: List[str] = Field(default_factory=list)


class FAQ(BaseModel):
    question: str
    answer: str


class Post(BaseModel):
    title: str
    description: str
    category: str                       # internal only — one of config.CATEGORIES
    tags: List[str] = Field(default_factory=list)
    lede: str
    sections: List[Section]
    faqs: List[FAQ] = Field(default_factory=list)
    # filled in by generate_post() after the model call
    slug: str = ""          # filename stem: YYYY-MM-DD-topic-slug
    topic_slug: str = ""    # just the topic part, date-independent — for dedup


_SCHEMA = """{
  "title": "string, 10-120 chars, includes the focus keyword + a local cue (Kochi/Kerala)",
  "description": "150-190 chars, compelling, contains the focus keyword — this is the Google search snippet",
  "category": "one of: Allergy | Pediatric | Migraine | Skin | General",
  "tags": ["2-5 short tags, e.g. Allergy, Sinusitis, Seasonal health"],
  "lede": "opening paragraph; use the focus keyword within the first sentence or two",
  "sections": [{"heading": "descriptive H2", "paragraphs": ["..."], "bullets": ["...optional..."]}],
  "faqs": [{"question": "string", "answer": "string"}]
}"""

# Fallback used only if content_prompt.txt is missing. The live, editable prompt
# lives in that repo file (edit on GitHub, or via Telegram /setprompt). Tokens
# {clinic} and {categories} are substituted at runtime.
DEFAULT_PROMPT = """You are a professional health content writer for {clinic}, a
homoeopathy clinic in Kochi, Kerala (Dr. Talal M and colleagues, BHMS). Write ONE
blog post that is genuinely useful, simple and clear for patients — not clinicians.

SEO: pick ONE focus keyword (a real local search phrase) and place it in the title,
description and first sentences. Weave in local terms naturally where relevant
(Kochi, Fort Kochi, Kerala, Ernakulam). No keyword-stuffing. Descriptive H2s.
Include 2-3 FAQs.

STYLE: warm, professional, simple and logical; short paragraphs; 600-1000 words;
3-4 sections.

MEDICAL CONTENT RULES (non-negotiable):
- Never use cure/guaranteed/"no side effects"/"100% safe"/miracle/"permanent
  cure"/"instant relief"/risk-free/"proven to cure" — no outcome promises, measured
  language only.
- Never suggest a reader should stop any prescribed medication, or skip, avoid,
  postpone or cancel a doctor-advised surgery, on their own.
- Never invent statistics, studies, or patient quotes.
- Never name a specific homeopathic remedy (that looks like prescribing without an
  in-person case-taking) — describe the APPROACH, not a remedy name.
- For anything that can be serious, include a clear line about when to seek
  in-person or urgent care rather than wait.

category MUST be exactly one of: {categories}."""


def _load_prompt() -> str:
    """Load the live content prompt from content_prompt.txt (editable on GitHub /
    via Telegram), falling back to DEFAULT_PROMPT. Appends the fixed JSON-shape
    footer."""
    try:
        base = open(config.PROMPT_FILE, encoding="utf-8").read().strip()
    except OSError:
        base = DEFAULT_PROMPT.strip()
    base = base.replace("{clinic}", config.CLINIC_NAME).replace(
        "{categories}", ", ".join(config.CATEGORIES))
    return (base + "\n\nReply with ONE JSON object and NOTHING else — no markdown "
            "fences, no commentary.\nThe JSON must match this shape exactly:\n" + _SCHEMA)


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "post"


def _clamp(s: str, lo: int, hi: int, pad_suffix: str = "") -> str:
    """Clamp a string into [lo, hi] chars — truncate cleanly if too long, pad with
    pad_suffix (repeated) if too short. Guarantees the site's Zod min/max always pass
    regardless of what the model produced."""
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > hi:
        s = s[:hi].rsplit(" ", 1)[0].rstrip(".,;: ") or s[:hi]
    while pad_suffix and len(s) < lo:
        s = (s + " " + pad_suffix).strip()
    return s


def _loads_lenient(s: str) -> dict:
    """json.loads with a best-effort repair pass for the JSON mistakes free models
    make most often: trailing commas, and MISSING commas between adjacent tokens
    separated by a newline. Each inserted comma is only between two complete
    tokens, where a comma is always required in valid JSON — so the repair never
    changes meaning. Still raises if unrepairable, which lets generate_post fall
    back to a model retry."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r",(\s*[}\]])", r"\1", s)            # drop trailing commas
    fixed = re.sub(r"}(\s*\n\s*)\{", r"},\1{", fixed)   # }{  -> },{
    fixed = re.sub(r"](\s*\n\s*)\[", r"],\1[", fixed)   # ][  -> ],[
    fixed = re.sub(r'"(\s*\n\s*)"', r'",\1"', fixed)     # "…" "…" -> "…","…"
    fixed = re.sub(r'}(\s*\n\s*)"', r'},\1"', fixed)     # } "key" -> },"key"
    fixed = re.sub(r'](\s*\n\s*)"', r'],\1"', fixed)     # ] "key" -> ],"key"
    return json.loads(fixed)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ``` fences / prose)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model reply")
    return _loads_lenient(t[start:end + 1])


def generate_post(topic: str, feedback: str = "") -> Post:
    """Generate structured post content via the currently-selected Cloudflare model.
    `feedback` is appended on regeneration. Retries once on a parse/validation error."""
    ask = f"Write the post for this topic:\n{topic}\n"
    if feedback:
        ask += (f"\nThe previous draft was REJECTED by the editor. Apply this "
                f"feedback and rewrite accordingly:\n{feedback}\n")
    messages = [{"role": "system", "content": _load_prompt()},
                {"role": "user", "content": ask}]
    last_err = None
    json_mode = True   # ask the API for guaranteed-valid JSON; drop if unsupported
    for attempt in range(3):
        kw = {"temperature": 0.6, "max_tokens": 4000}
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        try:
            resp = llm.chat(messages, **kw)
        except openai.BadRequestError:
            if json_mode:                 # model doesn't support JSON mode — retry plain
                json_mode = False
                continue
            raise
        raw = resp.choices[0].message.content or ""
        try:
            post = Post(**_extract_json(raw))
            if post.category not in config.CATEGORIES:
                post.category = config.CATEGORIES[0]
            # Deterministic clamps — guarantee the site's Zod schema (title 10-120,
            # description 50-200) always passes no matter what the model produced.
            post.title = _clamp(post.title, 10, 120)
            post.description = _clamp(post.description, 50, 200,
                                      pad_suffix=f"Guidance from {config.CLINIC_NAME}.")
            tags = [t.strip() for t in post.tags if t.strip()][:6]
            post.tags = tags or [post.category]
            today = datetime.date.today().isoformat()
            post.topic_slug = _slugify(post.title)
            post.slug = f"{today}-{post.topic_slug}"
            return post
        except (ValueError, ValidationError) as e:
            last_err = e
            messages.append({"role": "assistant", "content": raw[:2000]})
            messages.append({"role": "user", "content":
                             "That was not valid JSON for the required shape. "
                             "Reply again with ONLY the JSON object, no fences."})
    raise RuntimeError(f"model did not return valid post JSON: {last_err}")


def _yaml_str(s: str) -> str:
    """Double-quoted YAML scalar — escape backslashes and quotes."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_markdown(post: Post) -> str:
    """Render the Astro content-collection markdown file: frontmatter (matching
    src/content.config.ts in the site repo exactly) + a plain-markdown body. No
    disclaimer needed here — the site's blog layout ([...slug].astro) appends one
    to every post automatically."""
    today = datetime.date.today().isoformat()
    svc_slug, svc_label = config.CATEGORY_SERVICE[post.category]
    tags_yaml = "[" + ", ".join(_yaml_str(t) for t in post.tags) + "]"

    front = (
        "---\n"
        f"title: {_yaml_str(post.title)}\n"
        f"description: {_yaml_str(post.description)}\n"
        f"pubDate: {today}\n"
        f"tags: {tags_yaml}\n"
        "---\n"
    )

    body_parts = [post.lede.strip()]
    for s in post.sections:
        body_parts.append(f"## {s.heading.strip()}")
        for p in s.paragraphs:
            body_parts.append(p.strip())
        if s.bullets:
            body_parts.append("\n".join(f"- {b.strip()}" for b in s.bullets))
    if post.faqs:
        body_parts.append("## Common questions")
        for f in post.faqs:
            body_parts.append(f"**{f.question.strip()}**\n\n{f.answer.strip()}")
    body_parts.append(
        f"[More on {svc_label}](/services/{svc_slug}) · "
        f"[Ask about this on WhatsApp]({config.WA})"
    )
    body = "\n\n".join(body_parts) + "\n"
    return front + "\n" + body
