"""Talal Homeo daily blog agent — Telegram-controlled, fully automated: draft,
safety gate, publish. No manual approval step; Telegram is used for
status/control (/generate, /report-free, /settime, etc.), not for gating what
goes live.

Publishes into a SEPARATE, already-existing website repo (TalalHomeo, an Astro
site) — see bot/config.py REPO_DIR / GITHUB_REPO. This agent's own repo only
holds its code, content_prompt.txt and topics.md.

Run:  python -m bot.bot        (from the repo root, with bot/.env present)
"""
import asyncio
import datetime
import logging
import random
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes)

from . import config, content, llm, publisher, topics

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("talal-bot")

IST = ZoneInfo("Asia/Kolkata")


def _only_owner(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.id == config.TELEGRAM_CHAT_ID


def _preview(post) -> str:
    body = post.sections[0].paragraphs[0] if post.sections and post.sections[0].paragraphs else post.lede
    return (f"<b>{post.title}</b>\n"
            f"<i>{post.category} · {', '.join(post.tags)}</i>\n\n"
            f"{post.description}\n\n"
            f"{body[:300]}…\n\n"
            f"<code>src/content/blog/{post.slug}.md</code>")


MAX_TOPIC_ATTEMPTS = 3  # how many different auto-picked topics to try in one run
                        # before giving up for the day on repeated duplicate slugs


def _generate_blocking(topic: str | None, feedback: str = ""):
    """All the network/git/subprocess work — run off the event loop."""
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
        post = content.generate_post(topic, feedback)
        # Guard: never overwrite a live post. If this topic's slug is already
        # published (under any date), it's a duplicate.
        if not publisher.slug_is_published(post.topic_slug):
            break
        last_dup_msg = (f"duplicate: a post with slug '{post.topic_slug}' is "
                        f"already published. Topic was: {topic}.")
        if user_supplied_topic:
            raise RuntimeError(
                last_dup_msg + " Send /generate to try a fresh topic, or "
                "/addtopic a new angle.")
        topics.mark_done(topic, f"SKIPPED-DUPLICATE-{post.topic_slug}.md")
        log.warning("topic collided with an existing post, trying a different "
                   "one (attempt %d/%d): %s", attempt + 1, MAX_TOPIC_ATTEMPTS, topic)
        topic = None
    else:
        raise RuntimeError(
            f"Tried {MAX_TOPIC_ATTEMPTS} different auto-picked topics and every "
            f"one collided with an already-published post. Last: {last_dup_msg} "
            f"Consider /addtopic with a fresh, specific angle.")

    filename = f"{post.slug}.md"
    md = content.render_markdown(post)
    path = publisher.stage_draft(filename, md)
    ok, out = publisher.run_gate(path)
    if not ok:
        # one self-correction pass using the gate output as feedback
        post = content.generate_post(topic, feedback + "\nSafety/quality gate said:\n" + out)
        filename = f"{post.slug}.md"
        md = content.render_markdown(post)
        path = publisher.stage_draft(filename, md)
        ok, out = publisher.run_gate(path)
    return {"topic": topic, "post": post, "md": md, "filename": filename,
            "ok": ok, "gate": out, "auto": auto_note}


async def _publish_and_notify(context: ContextTypes.DEFAULT_TYPE, post, md, filename, topic):
    chat_id = config.TELEGRAM_CHAT_ID
    await context.bot.send_message(chat_id, "📤 Publishing…")
    try:
        url = await asyncio.to_thread(publisher.publish, post, md, filename, topic)
    except Exception as e:  # noqa
        log.exception("publish failed")
        await context.bot.send_message(chat_id, f"⚠️ Publish failed: {e}")
        return
    await context.bot.send_message(chat_id, f"✅ Published — live in ~1–2 min:\n{url}")


async def generate_and_send(context: ContextTypes.DEFAULT_TYPE, topic=None, feedback=""):
    """Generate a draft and, if it passes the safety gate, publish it immediately —
    no manual Telegram approval step. The gate (bot/check_post.py) is the only
    check before content goes live; a gate failure still stops publication."""
    chat_id = config.TELEGRAM_CHAT_ID
    await context.bot.send_message(chat_id, "✍️ Writing today's draft… (~1 min)")
    try:
        res = await asyncio.to_thread(_generate_blocking, topic, feedback)
    except Exception as e:  # noqa
        log.exception("generation failed")
        await context.bot.send_message(chat_id, f"⚠️ Generation failed: {e}")
        return
    if not res["ok"]:
        publisher.discard(res["filename"])
        await context.bot.send_message(
            chat_id, "⚠️ Draft did not pass the safety gate twice:\n"
                     f"<pre>{res['gate']}</pre>\nSend /generate to try a fresh topic.",
            parse_mode=ParseMode.HTML)
        return
    note = (f"🌶️ Auto-picked a trending topic: <i>{res['auto']}</i>\n\n"
            if res["auto"] else "")
    await context.bot.send_message(chat_id, note + _preview(res["post"]),
                                   parse_mode=ParseMode.HTML)
    await _publish_and_notify(context, res["post"], res["md"], res["filename"], res["topic"])


# ---------------- handlers ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    await update.message.reply_text(
        f"{config.CLINIC_NAME} blog agent.\n\n"
        "Every day I draft a post and, if it passes the safety gate, publish it "
        "automatically to the website. No approval tap needed; I'll message you "
        "here once it's live. The posting time varies daily within your set "
        "window (see /time).\n\n"
        "Commands:\n"
        "/generate – write and auto-publish a post right now\n"
        "/topics – show the topic queue\n"
        "/addtopic <topic> – add a topic to the queue\n"
        "/model – show the current writing model\n"
        "/models – list all available Cloudflare Workers AI models, numbered\n"
        "/setmodel <number> – switch to a model by its number from /models\n"
        "/time – show the daily post window + next scheduled run\n"
        "/settime HH:MM-HH:MM – set the daily post window (IST)\n"
        "/prompt – show the content-generation prompt\n"
        "/setprompt <text> – update the prompt (also editable on GitHub, in "
        "this agent's own repo)")


def _pick_random_slot() -> datetime.datetime:
    """Pick a fresh random minute inside the configured window, for today if that
    moment hasn't passed yet (with a 2-min safety buffer), otherwise tomorrow.
    A new random minute is drawn every time this is called — the daily posting
    time deliberately varies day to day rather than landing on a fixed minute."""
    start_s, end_s = config.get_post_window()
    sh, sm = (int(x) for x in start_s.split(":"))
    eh, em = (int(x) for x in end_s.split(":"))
    start_minutes = sh * 60 + sm
    end_minutes = max(eh * 60 + em, start_minutes)  # zero-width window still valid
    chosen = random.randint(start_minutes, end_minutes)
    ch, cm = divmod(chosen, 60)

    now = datetime.datetime.now(IST)
    candidate = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    if candidate <= now + datetime.timedelta(minutes=2):
        candidate += datetime.timedelta(days=1)
    return candidate


def _schedule_next_daily(job_queue):
    """(Re)schedule the next daily post as a one-shot run at a freshly-randomized
    time (see _pick_random_slot). Called at bot startup and again at the start of
    every daily_job run, so tomorrow's slot is always queued regardless of how
    today's run goes. Returns the scheduled datetime."""
    for j in job_queue.get_jobs_by_name("daily_post"):
        j.schedule_removal()
    when = _pick_random_slot()
    job_queue.run_once(daily_job, when=when, name="daily_post")
    return when


async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    start, end = config.get_post_window()
    jobs = context.job_queue.get_jobs_by_name("daily_post")
    next_run = jobs[0].next_t.astimezone(IST).strftime("%Y-%m-%d %H:%M") if jobs else "not scheduled"
    await update.message.reply_text(
        f"Daily post window: {start}–{end} IST (a new random minute is picked "
        f"inside it each day).\nNext run: {next_run} IST")


async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    args = " ".join(context.args).strip()
    start, _, end = args.partition("-")
    try:
        if not start or not end:
            raise ValueError("need start-end")
        val_start, val_end = config.set_post_window(start, end)
    except Exception:  # noqa
        await update.message.reply_text("Usage: /settime 06:00-09:00   (24-hour, IST)")
        return
    when = _schedule_next_daily(context.job_queue)
    await update.message.reply_text(
        f"Daily post window set to {val_start}–{val_end} IST.\n"
        f"Next run: {when.strftime('%Y-%m-%d %H:%M')} IST")


async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    text = publisher.read_prompt() or "(using built-in default prompt)"
    await update.message.reply_text(
        "Current content prompt (edit content_prompt.txt on GitHub in this "
        "agent's own repo, or send /setprompt followed by new text):\n\n" + text[:3500])


async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    parts = update.message.text.split(None, 1)
    body = parts[1].strip() if len(parts) > 1 else ""
    if len(body) < 40:
        await update.message.reply_text(
            "Send /setprompt followed by the full prompt text (keep the {clinic} and "
            "{categories} placeholders). Tip: edit content_prompt.txt on GitHub for long edits.")
        return
    await update.message.reply_text("Updating the content prompt on GitHub…")
    try:
        await asyncio.to_thread(publisher.update_prompt, body)
    except Exception as e:  # noqa
        log.exception("prompt update failed")
        await update.message.reply_text(f"⚠️ Prompt update failed: {e}")
        return
    await update.message.reply_text("✅ Content prompt updated and committed. "
                                    "It takes effect on the next /generate.")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    await update.message.reply_text(f"Current writing model:\n<code>{config.get_model()}</code>",
                                    parse_mode=ParseMode.HTML)


async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    await update.message.reply_text("Fetching the current available models from Cloudflare…")
    try:
        ids = await asyncio.to_thread(llm.list_models)
    except Exception as e:  # noqa
        log.exception("model list fetch failed")
        await update.message.reply_text(
            f"⚠️ Couldn't fetch the live list ({e}). Falling back to presets.")
        ids = list(config.PRESET_MODELS)
    if not ids:
        ids = list(config.PRESET_MODELS)
    config.set_model_menu(ids)          # persist the numbering for /setmodel <n>
    cur = config.get_model()
    lines = [f"{i} - {m}" + ("  ✅ current" if m == cur else "")
             for i, m in enumerate(ids, 1)]
    body = "\n".join(lines)
    tail = "\n\nSwitch with /setmodel <number> — e.g. /setmodel 3"
    # Telegram hard-limits messages at 4096 chars; chunk if the roster is huge.
    while body:
        chunk, body = body[:3500], body[3500:]
        if body:
            cut = chunk.rfind("\n")
            if cut > 0:
                body, chunk = chunk[cut + 1:] + body, chunk[:cut]
        await update.message.reply_text(
            f"Available Cloudflare models ({len(ids)}):\n\n{chunk}" + (tail if not body else ""))


async def cmd_setmodel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    arg = " ".join(context.args).strip()
    if not arg:
        await update.message.reply_text(
            "Usage: /setmodel <number>  (run /models to see the numbered list)\n"
            "You can also pass a full model id, e.g. /setmodel openai/gpt-oss-20b:free")
        return
    if arg.isdigit():
        menu = config.get_model_menu()
        if not menu:
            await update.message.reply_text(
                "No model list yet — run /models first, then /setmodel <number>.")
            return
        n = int(arg)
        if not (1 <= n <= len(menu)):
            await update.message.reply_text(
                f"Pick a number between 1 and {len(menu)} (run /models to see them).")
            return
        mid = menu[n - 1]
    else:
        mid = arg
    config.set_model(mid)
    await update.message.reply_text(f"Writing model set to:\n<code>{mid}</code>",
                                    parse_mode=ParseMode.HTML)


async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    await generate_and_send(context)


async def cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    q = topics.list_queue()
    if not q:
        await update.message.reply_text("Queue is empty — I'll auto-pick a timely topic next run.")
        return
    lines = "\n".join(f"{i+1}. {t}" for i, t in enumerate(q[:20]))
    await update.message.reply_text(f"Topic queue ({len(q)}):\n{lines}")


async def cmd_addtopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _only_owner(update):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /addtopic [Allergy] Why sinusitis flares every monsoon")
        return
    added = topics.add_topic(text)
    await update.message.reply_text(f"Added to the queue:\n{added}")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Model-picker buttons (kept for parity, currently unused since /models
    lists numbers to select via /setmodel instead)."""
    q = update.callback_query
    await q.answer()
    if q.message.chat.id != config.TELEGRAM_CHAT_ID:
        return
    if q.data.startswith("m:"):
        idx = int(q.data[2:])
        model = config.PRESET_MODELS[idx]
        config.set_model(model)
        await q.edit_message_text(f"Writing model set to:\n{model}")


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    # Reschedule tomorrow's (freshly randomized) slot FIRST, so a next run is
    # always queued even if today's generation fails or the process crashes.
    _schedule_next_daily(context.job_queue)
    await generate_and_send(context)


WATCHDOG_INTERVAL_SECONDS = 3 * 60 * 60  # check every 3h


async def _scheduling_watchdog(context: ContextTypes.DEFAULT_TYPE):
    """Safety net for the daily-post self-rescheduling chain. daily_job() is the
    ONLY place that queues tomorrow's slot — if it ever fails to run (a
    scheduler misfire, an unhandled exception, the job getting removed some
    other way) nothing else would notice, and auto-posting silently stops
    forever with no error and no alert. This runs on a fixed interval
    (independent of the fragile chain) and re-queues + alerts if the
    daily_post job has gone missing."""
    jobs = context.job_queue.get_jobs_by_name("daily_post")
    if jobs:
        return  # healthy — a slot is queued, nothing to do
    log.warning("scheduling watchdog: no daily_post job found — rescheduling now")
    when = _schedule_next_daily(context.job_queue)
    try:
        await context.bot.send_message(
            config.TELEGRAM_CHAT_ID,
            "⚠️ Auto-post scheduling had silently stopped (no post was queued) — "
            f"I've fixed it.\nNext auto-post: {when.strftime('%Y-%m-%d %H:%M')} IST.")
    except Exception:  # noqa
        log.exception("watchdog: failed to send the recovery alert")


def _schedule_watchdog(job_queue):
    for j in job_queue.get_jobs_by_name("scheduling_watchdog"):
        j.schedule_removal()
    job_queue.run_repeating(_scheduling_watchdog, interval=WATCHDOG_INTERVAL_SECONDS,
                            first=120, name="scheduling_watchdog")


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global handler so unexpected exceptions (e.g. a transient Telegram
    Conflict/NetworkError from getUpdates) are logged cleanly instead of PTB's
    default "No error handlers are registered" noise. Deliberately does not
    message the user here — Telegram itself may be the thing failing; the
    scheduling watchdog is the mechanism that actually alerts on the one
    failure mode (silent auto-post stoppage) that matters most."""
    log.error("Unhandled exception", exc_info=context.error)


def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(_on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("topics", cmd_topics))
    app.add_handler(CommandHandler("addtopic", cmd_addtopic))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("models", cmd_models))
    app.add_handler(CommandHandler("setmodel", cmd_setmodel))
    app.add_handler(CommandHandler("time", cmd_time))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("prompt", cmd_prompt))
    app.add_handler(CommandHandler("setprompt", cmd_setprompt))
    app.add_handler(CallbackQueryHandler(on_button))

    when = _schedule_next_daily(app.job_queue)
    _schedule_watchdog(app.job_queue)
    log.info("Talal Homeo bot started. Next auto-post at %s IST. Publishing to '%s'.",
             when.strftime("%Y-%m-%d %H:%M"), config.GITHUB_REPO)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
