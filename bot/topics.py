"""Topic queue management — read/add/consume topics in topics.md (this agent's
own repo, NOT the site repo), and auto-pick a timely, useful topic via the
current model when the queue is empty."""
import re
import datetime
from . import config, llm

_QUEUE_HDR = "## Queue (oldest first = next up)"
_DONE_HDR = "## Done (most recent first)"


def _read():
    with open(config.TOPICS_FILE, encoding="utf-8") as f:
        return f.read()


def _write(text):
    with open(config.TOPICS_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def _split(text):
    """Return (head, queue_lines, done_block)."""
    qi = text.index(_QUEUE_HDR) + len(_QUEUE_HDR)
    di = text.index(_DONE_HDR)
    head = text[: text.index(_QUEUE_HDR) + len(_QUEUE_HDR)]
    queue_raw = text[qi:di]
    done_block = text[di:]
    queue_lines = [l for l in queue_raw.splitlines() if l.strip().startswith("- ")]
    return head, queue_lines, done_block


def list_queue():
    _, q, _ = _split(_read())
    return [l.strip()[2:].strip() for l in q]


def list_done_titles():
    """Return the '[Category] Title' of every already-published post (newest first),
    stripped of the leading date and trailing '-> filename.md'. Used to stop the
    auto-picker from proposing a topic that has already been covered."""
    _, _, done = _split(_read())
    titles = []
    for l in done.splitlines():
        l = l.strip()
        if not l.startswith("- "):
            continue
        body = l[2:].strip()
        body = re.sub(r"^\d{4}-\d{2}-\d{2}\s+", "", body)          # leading date
        body = re.sub(r"\s*->\s*\S+\.md\s*$", "", body)            # trailing filename
        if body:
            titles.append(body.strip())
    return titles


def queue_count():
    return len(list_queue())


def add_topic(topic: str):
    """Append a topic to the bottom of the queue. Returns the cleaned topic line."""
    topic = topic.strip()
    if not topic.startswith("["):
        topic = "[General] " + topic  # tag optional; agent tolerates it
    text = _read()
    head, q, done = _split(text)
    q.append(f"- {topic}")
    new = head + "\n" + "\n".join(q) + "\n\n" + done
    _write(new)
    return topic


def next_topic():
    """Return the first queued topic string (without removing it), or None."""
    q = list_queue()
    return q[0] if q else None


def mark_done(topic: str, filename: str):
    """Move a topic from Queue to Done with today's date + filename."""
    text = _read()
    head, q, done = _split(text)
    q = [l for l in q if l.strip()[2:].strip() != topic.strip()]
    today = datetime.date.today().isoformat()
    done_lines = done.splitlines()
    insert_at = 1 if len(done_lines) > 1 else len(done_lines)
    done_lines.insert(insert_at, f"- {today} {topic}  -> {filename}")
    new = head + "\n" + "\n".join(q) + "\n\n" + "\n".join(done_lines) + "\n"
    _write(new)


def autoselect_viral_topic() -> str:
    """Ask the current Cloudflare Workers AI model for ONE timely, shareable,
    healthcare-relevant blog topic suited to the clinic. Returns a
    '[Category] Title' line."""
    cats = " / ".join(config.CATEGORIES)
    today = datetime.date.today()
    month = today.strftime("%B")
    # Give the model the full list of already-published topics so it never repeats one.
    already = list_done_titles()
    avoid_block = ""
    if already:
        avoid_block = (
            "\n\nThese topics have ALREADY been published — do NOT propose any of "
            "them again, and avoid anything that overlaps closely in subject or "
            "angle:\n" + "\n".join(f"- {t}" for t in already)
            + "\n\nPropose something genuinely NEW that is not a rewording of the above."
        )
    resp = llm.chat(
        temperature=0.8,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"You plan content for {config.CLINIC_NAME}, a homoeopathy clinic "
                f"in Kochi, Kerala. Categories: {cats}.\n"
                f"It is {month} {today.year} on the Kerala coast. Considering the "
                "current season, typical weather, and health concerns common at "
                "this time of year (Kochi's humidity, monsoon-linked allergic "
                "rhinitis and sinusitis, common childhood ENT concerns like "
                "adenoids and tonsillitis, etc.), propose ONE blog topic that is "
                "timely, highly shareable, and genuinely useful. It MUST map to "
                "one of the categories and stay within safe, non-overclaiming "
                "homoeopathy content."
                + avoid_block
                + "\n\nReply with EXACTLY one line and nothing else, in this format:\n"
                "[Category] Title of the post"
            ),
        }],
    )
    text = (resp.choices[0].message.content or "").strip()
    line = next((l.strip() for l in reversed(text.splitlines())
                 if re.match(r"^\[[A-Za-z]+\]\s+.+", l.strip())), None)
    if not line:
        line = "[General] Seasonal health on the Kerala coast: a gentle homoeopathic perspective"
    return line
