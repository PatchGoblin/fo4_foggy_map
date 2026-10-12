"""Pushing a built site folder to a git remote, for a host such as Amplify to deploy.

Plumbing against a private bare repository, so there is no checkout to corrupt when the
game kills the companion mid-publish. Every publish is a single commit with no parent,
force-pushed: the site repo holds the current site and nothing else, and never grows.

The author is always the one configured for publishing. The global git identity is
never used, because for some people that is their real name.
"""

from __future__ import annotations

import os
import subprocess

from foggymap.identity import default_terms, find_leaks

# Long enough for a slow upload; short enough that a hung credential prompt cannot
# stall publishing forever.
TIMEOUT_S = 180


class PublishError(Exception):
    """Publishing did not happen, with the reason in plain words."""


def push_site(
    staging_dir, repo_dir, remote: str, branch: str,
    author_name: str, author_email: str,
    git: str = "git", leak_terms: list[str] | None = None,
) -> str:
    """Commit everything in ``staging_dir`` as the whole site and push it. Returns the sha."""
    if not author_name or not author_email:
        raise PublishError("AuthorName and AuthorEmail must both be set in publish.ini")

    terms = default_terms() if leak_terms is None else leak_terms
    leaks = find_leaks(str(staging_dir), terms)
    if leaks:
        named = ", ".join(sorted({relative for relative, _ in leaks}))
        raise PublishError(f"refusing to publish: identifying text found in {named}")

    repo_dir = str(repo_dir)
    if not os.path.isdir(repo_dir):
        _run(git, ["init", "--bare", "-q", repo_dir], "init")

    # Only publishing uses this repo, one publish at a time, so any lock is left over
    # from a publish that was killed.
    index = os.path.join(repo_dir, "index")
    for leftover in (index + ".lock", index):
        if os.path.exists(leftover):
            os.remove(leftover)

    base = ["-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
            "--git-dir", repo_dir, "--work-tree", str(staging_dir)]
    env = {
        "GIT_AUTHOR_NAME": author_name, "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name, "GIT_COMMITTER_EMAIL": author_email,
    }
    _run(git, base + ["add", "-A", "."], "add", cwd=staging_dir)
    tree = _run(git, base + ["write-tree"], "write-tree")
    sha = _run(git, base + ["commit-tree", tree, "-m", "Publish exploration progress"],
               "commit", env=env)
    _run(git, base + ["push", "--force", "--quiet", remote, f"{sha}:refs/heads/{branch}"],
         "push")
    return sha


def _run(git: str, args: list[str], what: str, cwd=None, env=None) -> str:
    full_env = dict(os.environ, GIT_TERMINAL_PROMPT="0", **(env or {}))
    try:
        result = subprocess.run(
            [git, *args], cwd=None if cwd is None else str(cwd), env=full_env,
            capture_output=True, text=True, timeout=TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublishError(f"git {what} failed: {type(error).__name__}: {error}") from error
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip()
        raise PublishError(f"git {what} failed (exit {result.returncode}): {reason}")
    return result.stdout.strip()
