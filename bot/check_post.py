"""
check_post.py — deterministic safety + quality gate for Talal Homeo blog posts.

Mirrors two things that live in the SEPARATE site repo (TalalHomeo) so a bad post
never gets pushed there in the first place:
  1. The frontmatter contract enforced by src/content.config.ts at build time
     (title/description length, tags count, pubDate shape) — a mismatch here
     would fail that repo's CI build.
  2. The content rules in BLOG-AGENT-SPEC.md (no cure claims, no telling readers
     to stop meds/skip surgery, no fabricated stats, no remedy names).

The daily agent MUST run this on any new post before publishing.
Exit 0 = pass. Exit 1 = FAIL (do not publish; fix and re-run).

Usage:  python -m bot.check_post <path-to-post.md>
"""
import sys
import re
import os

# Medical-overclaim words banned on a YMYL health site (case-insensitive, word-ish match).
BANNED = [
    "cure", "cures", "cured", "guaranteed", "guarantee",
    "no side effects", "100% safe", "completely safe", "miracle",
    "permanent cure", "instant relief", "risk-free", "proven to cure",
]

# Telling a reader to stop prescribed medication or skip/avoid advised surgery is
# explicitly banned by BLOG-AGENT-SPEC.md — it's medical advice this agent must
# never give.
BANNED_ADVICE = [
    "stop taking your medication", "stop your medication", "stop your prescribed",
    "stop your prescription", "discontinue your medication",
    "skip the surgery", "skip your surgery", "avoid the surgery", "avoid surgery",
    "cancel the surgery", "cancel your surgery", "postpone the surgery",
    "postpone your surgery", "no need for surgery", "instead of surgery",
    "without surgery",
]

# Specific homeopathic remedy/medicine names must never appear in patient-facing
# posts — naming remedies looks like prescribing without a case-taking consultation.
BANNED_REMEDY_NAMES = [
    "belladonna", "hepar sulphur", "hepar sulph", "phytolacca", "kali bichromicum",
    "kali bich", "arsenicum", "pulsatilla", "nux vomica", "bryonia", "rhus tox",
    "sulphur", "calcarea", "lycopodium", "natrum mur", "sepia", "ignatia",
    "apis mellifica", "apis mel", "silicea", "phosphorus", "thuja", "lachesis",
    "mercurius", "gelsemium", "aconite", "aconitum", "graphites", "conium",
    "hypericum", "arnica", "ledum", "ruta", "staphysagria", "china officinalis",
]

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")


def _parse_frontmatter(text: str):
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    raw, body = m.group(1), m.group(2)
    fm = {}
    # tiny hand-parser — the fields we emit are always flat scalars/lists of
    # quoted strings, so a full YAML parser would be overkill.
    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = re.findall(r'"((?:[^"\\]|\\.)*)"', val)
            fm[key] = [i.replace('\\"', '"').replace("\\\\", "\\") for i in items]
        elif val.startswith('"') and val.endswith('"') and len(val) >= 2:
            fm[key] = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        else:
            fm[key] = val
    return fm, body


def visible_text(md: str) -> str:
    # strip markdown link/emphasis markup, lowercase — for the safety scans
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)  # [text](url) -> text
    text = re.sub(r"[*_`#>-]", " ", text)
    return re.sub(r"\s+", " ", text).lower()


def main(path):
    if not os.path.isfile(path):
        print(f"FAIL: file not found: {path}")
        return 1
    raw_text = open(path, encoding="utf-8").read()
    fails = []

    basename = os.path.basename(path)
    if not _FILENAME_RE.match(basename):
        fails.append(f"filename must match YYYY-MM-DD-slug.md: got '{basename}'")

    fm, body = _parse_frontmatter(raw_text)
    if fm is None:
        fails.append("no valid --- frontmatter block found")
        fm, body = {}, raw_text

    title = fm.get("title", "")
    if not (10 <= len(title) <= 120):
        fails.append(f"title must be 10-120 chars: got {len(title)}")

    description = fm.get("description", "")
    if not (50 <= len(description) <= 200):
        fails.append(f"description must be 50-200 chars: got {len(description)}")

    pub_date = fm.get("pubDate", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(pub_date)):
        fails.append(f"pubDate must be YYYY-MM-DD: got '{pub_date}'")

    tags = fm.get("tags", [])
    if not isinstance(tags, list) or not (1 <= len(tags) <= 6):
        fails.append(f"tags must be a list of 1-6 items: got {tags!r}")

    if re.search(r"<[a-zA-Z][^>]*>", body):
        fails.append("body contains raw HTML — plain markdown only")

    stripped_body = body.strip()
    if stripped_body and not stripped_body.startswith("#"):
        pass  # fine — starts with a plain paragraph (the lede)
    if re.search(r"^#\s", stripped_body, re.M):
        fails.append("body must start below the page title — use ## for headings, not #")

    text = visible_text(body)

    for word in BANNED:
        if re.search(r"\b" + re.escape(word) + r"\b", text):
            fails.append(f"banned overclaim word present: '{word}'")

    for phrase in BANNED_ADVICE:
        if phrase in text:
            fails.append(f"banned medical-advice phrase present: '{phrase}'")

    for remedy in BANNED_REMEDY_NAMES:
        if re.search(r"\b" + re.escape(remedy) + r"\b", text):
            fails.append(f"specific remedy name must not appear in patient-facing content: '{remedy}'")

    words = len(text.split())
    # hard floor blocks spam-thin content; BLOG-AGENT-SPEC.md targets 600-1200 words.
    if words < 400:
        fails.append(f"article too thin: {words} words (need >= 400; aim 600-1200)")

    if fails:
        print(f"FAIL ({len(fails)}) — {path}")
        for f in fails:
            print("  - " + f)
        return 1
    print(f"PASS ({words} words) — {path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m bot.check_post <path-to-post.md>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
