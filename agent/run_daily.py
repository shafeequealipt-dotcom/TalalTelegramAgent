"""Daily entrypoint — run once (via a systemd timer, see agent/deploy/) to
generate, safety-gate and publish exactly one post into the site repo.

No persistent process, no scheduling logic here: the systemd timer's
`OnCalendar` + `RandomizedDelaySec` reproduce the "randomized time within a
daily window" behaviour the Telegram-controlled original did in-process.
Logs go to stdout — captured by `journalctl -u talal-agent`.

Usage:
    python -m agent.run_daily                  # take the next queued topic,
                                                 # or auto-pick one
    python -m agent.run_daily --topic "[Skin] Why hard water dries out hair"
"""
import argparse
import logging
import sys

from . import config, content, publisher, topics

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("talal-agent")

MAX_TOPIC_ATTEMPTS = 3  # how many different auto-picked topics to try in one run
                        # before giving up for the day on repeated duplicate slugs


def generate_and_publish(topic: str | None = None, feedback: str = "") -> int:
    """Returns a process exit code: 0 on a successful publish, 1 otherwise."""
    publisher.sync_main()
    auto_note = None
    user_supplied_topic = topic is not None
    post = None
    filename = None
    last_dup_msg = None

    for attempt in range(MAX_TOPIC_ATTEMPTS):
        if topic is None:
            topic = topics.next_topic()
            if topic is None:
                topic = topics.autoselect_viral_topic()
                topics.add_topic(topic)
                auto_note = topic
                log.info("queue empty — auto-picked topic: %s", topic)
        log.info("generating draft for topic: %s", topic)
        post = content.generate_post(topic, feedback)
        if not publisher.slug_is_published(post.topic_slug):
            break
        last_dup_msg = (f"duplicate: a post with slug '{post.topic_slug}' is "
                        f"already published. Topic was: {topic}.")
        if user_supplied_topic:
            log.error(last_dup_msg)
            return 1
        topics.mark_done(topic, f"SKIPPED-DUPLICATE-{post.topic_slug}.md")
        log.warning("topic collided with an existing post, trying a different "
                   "one (attempt %d/%d): %s", attempt + 1, MAX_TOPIC_ATTEMPTS, topic)
        topic = None
    else:
        log.error("tried %d different auto-picked topics and every one "
                 "collided with an already-published post. Last: %s",
                 MAX_TOPIC_ATTEMPTS, last_dup_msg)
        return 1

    filename = f"{post.slug}.md"
    md = content.render_markdown(post)
    path = publisher.stage_draft(filename, md)
    ok, out = publisher.run_gate(path)
    if not ok:
        log.warning("gate failed, retrying once with feedback:\n%s", out)
        post = content.generate_post(topic, feedback + "\nSafety/quality gate said:\n" + out)
        filename = f"{post.slug}.md"
        md = content.render_markdown(post)
        path = publisher.stage_draft(filename, md)
        ok, out = publisher.run_gate(path)
    if not ok:
        publisher.discard(filename)
        log.error("draft failed the safety gate twice — not publishing:\n%s", out)
        return 1

    if auto_note:
        log.info("auto-picked topic: %s", auto_note)
    try:
        url = publisher.publish(post, md, filename, topic)
    except Exception:  # noqa
        log.exception("publish failed")
        return 1
    log.info("published: %s", url)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", help="Use this exact topic instead of the queue/auto-pick.")
    parser.add_argument("--feedback", default="", help="Extra instructions for this generation.")
    args = parser.parse_args()
    sys.exit(generate_and_publish(args.topic, args.feedback))


if __name__ == "__main__":
    main()
