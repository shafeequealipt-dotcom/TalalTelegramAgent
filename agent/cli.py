"""Manual control, run over SSH on the server in place of the Telegram commands
the DNHCare original used.

    python -m agent.cli generate                     # write + publish one post now
    python -m agent.cli generate --topic "[Skin] ..." # force a specific topic
    python -m agent.cli topics                        # show the queue
    python -m agent.cli add-topic "[Allergy] ..."      # queue a topic
    python -m agent.cli models                        # list current Cloudflare models
    python -m agent.cli set-model <id-or-number>       # switch the writing model
    python -m agent.cli prompt                         # show the content prompt
    python -m agent.cli set-prompt path/to/file.txt     # update + commit the prompt
    python -m agent.cli gbp                            # Google Business Profile status
    python -m agent.cli gbp on | off                   # toggle the GBP auto-post
    python -m agent.cli gbp cta call | learn           # switch the post's button
    python -m agent.cli gbp preview <post-file.md>     # show the GBP text for a published post
    python -m agent.cli gbp share <post-file.md>       # post it to GBP now (test / re-share)
"""
import argparse
import os
import sys

from . import check_post, config, content, gbp, llm, publisher, topics
from .run_daily import generate_and_publish


def cmd_generate(args):
    sys.exit(generate_and_publish(args.topic, args.feedback or ""))


def cmd_topics(args):
    q = topics.list_queue()
    if not q:
        print("Queue is empty — the next run will auto-pick a topic.")
        return
    for i, t in enumerate(q, 1):
        print(f"{i}. {t}")


def cmd_add_topic(args):
    added = topics.add_topic(args.topic)
    print(f"Added: {added}")


def cmd_models(args):
    try:
        ids = llm.list_models()
    except Exception as e:  # noqa
        print(f"Couldn't fetch the live list ({e}). Falling back to presets.")
        ids = list(config.PRESET_MODELS)
    cur = config.get_model()
    for i, m in enumerate(ids, 1):
        marker = "  <- current" if m == cur else ""
        print(f"{i}. {m}{marker}")


def cmd_set_model(args):
    arg = args.model
    if arg.isdigit():
        try:
            ids = llm.list_models()
        except Exception:  # noqa
            ids = list(config.PRESET_MODELS)
        n = int(arg)
        if not (1 <= n <= len(ids)):
            print(f"Pick a number between 1 and {len(ids)} (run `models` to see them).")
            return
        arg = ids[n - 1]
    config.set_model(arg)
    print(f"Writing model set to: {arg}")


def cmd_prompt(args):
    print(publisher.read_prompt() or "(using built-in default prompt)")


def cmd_set_prompt(args):
    text = open(args.file, encoding="utf-8").read()
    if len(text.strip()) < 40:
        print("That file looks too short to be a real prompt — aborting.")
        return
    publisher.update_prompt(text)
    print("Content prompt updated and committed.")


def _gbp_from_published(filename: str):
    """Build the GBP text + link for a blog post that is already published. Used
    for a first live test and to re-share after a day when the GBP step failed."""
    name = os.path.basename(filename)
    if not name.endswith(".md"):
        name += ".md"
    with open(os.path.join(config.BLOG_DIR, name), encoding="utf-8") as f:
        fm, body = check_post._parse_frontmatter(f.read())
    paras = [p.strip() for p in body.split("\n\n") if p.strip() and p.strip()[0] not in "#-*[>"]
    post = content.Post(title=fm["title"], description=fm["description"],
                        category=config.CATEGORIES[0], sections=[],
                        lede=paras[0] if paras else fm["description"])
    return content.gbp_blurb(post), f"{config.SITE_URL}/blog/{name[:-3]}"


def cmd_gbp(args):
    a = [x.lower() for x in args.args]
    if a[:1] in (["preview"], ["share"]) and len(a) == 2:
        blurb, url = _gbp_from_published(args.args[1])
        print(f"Link: {url}\nButton: {config.gbp_cta()}\nText ({len(blurb)} chars):\n{blurb}\n")
        if a[0] == "share":
            if not gbp.is_configured():
                print("GBP is not configured — nothing posted.")
                return
            if not gbp.wait_until_live(url, timeout=30, interval=5):
                print("That page is not live on the site — nothing posted.")
                return
            print("Posted:", gbp.create_local_post(blurb, url))
        return
    if a[:1] in (["on"], ["off"]):
        config.set_gbp_enabled(a[0] == "on")
    elif a[:1] == ["cta"] and len(a) == 2 and a[1] in ("call", "learn", "learn_more"):
        config.set_gbp_cta(a[1])
    elif a:
        print("Usage: gbp | gbp on | gbp off | gbp cta call|learn | gbp preview <file> | gbp share <file>")
        return
    if not gbp.is_configured():
        print("Google Business Profile is NOT configured — the agent publishes the "
              "blog only. See SETUP.md (Google Business Profile).")
        return
    print(f"GBP auto-post: {'ON' if config.gbp_enabled() else 'OFF'}")
    print("CTA button: " + ("Call now (blog URL as plain text in the post)"
                            if config.gbp_cta() == "CALL" else "Learn more (links to the blog post)"))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("generate", help="Write and publish one post now.")
    p.add_argument("--topic")
    p.add_argument("--feedback", default="")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("topics", help="Show the topic queue.")
    p.set_defaults(func=cmd_topics)

    p = sub.add_parser("add-topic", help="Add a topic to the queue.")
    p.add_argument("topic")
    p.set_defaults(func=cmd_add_topic)

    p = sub.add_parser("models", help="List current Cloudflare Workers AI models.")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("set-model", help="Switch the writing model (id or number from `models`).")
    p.add_argument("model")
    p.set_defaults(func=cmd_set_model)

    p = sub.add_parser("prompt", help="Show the current content-generation prompt.")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("set-prompt", help="Update the prompt from a local file and commit it.")
    p.add_argument("file")
    p.set_defaults(func=cmd_set_prompt)

    p = sub.add_parser("gbp", help="Google Business Profile: status / on / off / cta call|learn.")
    p.add_argument("args", nargs="*")
    p.set_defaults(func=cmd_gbp)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
