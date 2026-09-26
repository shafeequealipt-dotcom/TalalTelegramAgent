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
"""
import argparse
import sys

from . import config, llm, publisher, topics
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
