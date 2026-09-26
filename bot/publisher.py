"""Publish flow: stage a draft into the SITE repo (TalalHomeo, checked out at
config.REPO_DIR), run the safety gate, and on pass commit/push straight to
main — Astro's own build (triggered by that push, see the site's
.github/workflows/deploy.yml) generates the post page, the blog index and
sitemap.xml automatically. No manual index/sitemap editing needed here, unlike
the DNHCare original this agent is patterned on: Astro's content collections
do that work.

A second, SEPARATE git target is this agent's OWN repo (config.AGENT_REPO_DIR) —
used only by update_prompt() for the /setprompt command, so content_prompt.txt
stays editable "on GitHub" without ever touching the site repo's history.
"""
import os
import sys
import subprocess
from . import config, topics


def _git(repo_dir, *args, check=True):
    return subprocess.run(["git", "-C", repo_dir, *args],
                          capture_output=True, text=True, check=check)


def sync_main():
    """Reset the local site clone to a clean origin/<publish-branch> before generating."""
    br = config.PUBLISH_BRANCH
    _git(config.REPO_DIR, "fetch", "origin")
    _git(config.REPO_DIR, "checkout", br)
    _git(config.REPO_DIR, "reset", "--hard", f"origin/{br}")
    _git(config.REPO_DIR, "clean", "-fd", os.path.relpath(config.BLOG_DIR, config.REPO_DIR))


def stage_draft(filename, content):
    """Write the post file (uncommitted) so the gate can read it. Returns path."""
    os.makedirs(config.BLOG_DIR, exist_ok=True)
    path = os.path.join(config.BLOG_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def run_gate(path):
    """Run bot/check_post.py. Returns (ok: bool, output: str)."""
    p = subprocess.run([sys.executable, config.CHECK_SCRIPT, path],
                       cwd=config.AGENT_REPO_DIR, capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def discard(filename):
    path = os.path.join(config.BLOG_DIR, filename)
    if os.path.exists(path):
        os.remove(path)


def slug_is_published(topic_slug: str) -> bool:
    """True if a post with this topic slug (the filename minus its leading
    YYYY-MM-DD- date and .md extension) is ALREADY committed to git — i.e. a
    real, live duplicate, regardless of which date it was published under.
    Checks git-tracked files — not the working tree — so an in-flight draft or
    a gate-retry re-write of the same slug is NOT flagged."""
    p = subprocess.run(["git", "ls-files", os.path.relpath(config.BLOG_DIR, config.REPO_DIR)],
                       cwd=config.REPO_DIR, capture_output=True, text=True)
    if p.returncode != 0:
        return False
    for line in p.stdout.splitlines():
        name = os.path.basename(line.strip())
        stem = name[:-3] if name.endswith(".md") else name
        # strip a leading YYYY-MM-DD- date prefix, if present
        parts = stem.split("-", 3)
        existing_slug = parts[3] if len(parts) == 4 and all(p.isdigit() for p in parts[:3]) else stem
        if existing_slug == topic_slug:
            return True
    return False


def read_prompt():
    """Return the current content prompt text."""
    try:
        return open(config.PROMPT_FILE, encoding="utf-8").read()
    except OSError:
        return ""


def update_prompt(text):
    """Overwrite content_prompt.txt and commit/push it to THIS AGENT'S OWN repo
    (never the site repo)."""
    with open(config.PROMPT_FILE, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    _git(config.AGENT_REPO_DIR, "add", os.path.relpath(config.PROMPT_FILE, config.AGENT_REPO_DIR))
    commit = _git(config.AGENT_REPO_DIR, "-c", "user.name=Talal Homeo Bot",
                 "-c", "user.email=bot@drtalalhomeo.in",
                 "commit", "-m", "agent: update content prompt", check=False)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        raise RuntimeError("git commit failed:\n" + commit.stderr)
    remote = (f"https://x-access-token:{config.AGENT_GITHUB_TOKEN}@github.com/"
              f"{config.AGENT_GITHUB_REPO}.git")
    push = _git(config.AGENT_REPO_DIR, "push", remote, config.PUBLISH_BRANCH, check=False)
    if push.returncode != 0:
        raise RuntimeError("git push failed:\n" + push.stderr)


def publish(post, content, filename, topic):
    """Re-sync main, re-write the held draft, commit & push main (fast-forward
    guaranteed) — Astro's build does the rest. Returns the live URL."""
    sync_main()                          # ensure fast-forward + clean base
    stage_draft(filename, content)       # re-write the post (sync may have cleaned it)
    topics.mark_done(topic, filename)

    rel_path = os.path.relpath(os.path.join(config.BLOG_DIR, filename), config.REPO_DIR)
    _git(config.REPO_DIR, "add", rel_path)
    _git(config.REPO_DIR, "-c", "user.name=Talal Homeo Bot",
         "-c", "user.email=bot@drtalalhomeo.in",
         "commit", "-m", f"blog: {post.title}")
    remote = (f"https://x-access-token:{config.GITHUB_TOKEN}@github.com/"
              f"{config.GITHUB_REPO}.git")
    push = _git(config.REPO_DIR, "push", remote, config.PUBLISH_BRANCH, check=False)
    if push.returncode != 0:
        raise RuntimeError("git push failed:\n" + push.stderr)
    return f"{config.SITE_URL}/blog/{filename[:-3]}"
