"""Deciding when to publish exploration progress, and reading publish.ini.

Publishing is off unless the player writes a ``publish.ini`` beside the plugin's data.
When on, the companion publishes at startup if anything is unpublished, then at most
once per interval of play, and only when the recorded data has actually changed.
"""

from __future__ import annotations

import configparser
import contextlib
import hashlib
import json
import msvcrt
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from foggymap.gitpublish import PublishError, push_site
from foggymap.history import EVENTS_FILE, Timeline
from foggymap.pipeline import MANIFEST_NAME, load_manifest
from foggymap.publish import build_site, default_template_dir

CONFIG_NAME = "publish.ini"

# After a failure, try again this soon rather than waiting out a whole interval -- but
# not every second, which would hammer the remote while offline.
RETRY_S = 5 * 60.0


@dataclass(frozen=True)
class PublishConfig:
    remote: str
    branch: str = "main"
    author_name: str = ""
    author_email: str = ""
    interval_minutes: float = 60.0
    git: str = "git"
    leak_check: bool = True
    # Off by default: players often give the character their own first name.
    show_character_name: bool = False
    # An MO2 profile folder. Set, the page lists every enabled mod as MO2 does; unset,
    # only the plugins and DLLs the game loaded.
    mo2_profile: str = ""


def load_publish_config(data_dir) -> PublishConfig | None:
    """The settings from ``publish.ini``, or None when publishing is off.

    Turned on but unusable raises rather than returning None: someone who enabled
    publishing should hear why nothing appears.
    """
    path = os.path.join(str(data_dir), CONFIG_NAME)
    if not os.path.isfile(path):
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # keys as written
    parser.read(path, encoding="utf-8")
    section = parser["Publish"] if parser.has_section("Publish") else {}
    if not _truthy(section.get("Enabled", "0")):
        return None

    remote = section.get("Remote", "").strip()
    if not remote:
        raise PublishError(f"{CONFIG_NAME} enables publishing but sets no Remote")
    try:
        interval = float(section.get("IntervalMinutes", "60"))
    except ValueError as error:
        raise PublishError(f"{CONFIG_NAME}: IntervalMinutes is not a number") from error
    return PublishConfig(
        remote=remote,
        branch=section.get("Branch", "main").strip() or "main",
        author_name=section.get("AuthorName", "").strip(),
        author_email=section.get("AuthorEmail", "").strip(),
        interval_minutes=interval,
        git=section.get("Git", "git").strip() or "git",
        leak_check=_truthy(section.get("LeakCheck", "1")),
        show_character_name=_truthy(section.get("ShowCharacterName", "0")),
        mo2_profile=section.get("MO2Profile", "").strip().strip('"'),
    )


class Publisher:
    """Publishes when due. ``tick`` is called from the watch loop on every pass."""

    def __init__(self, config: PublishConfig, assets_dir, data_dir,
                 clock=time.monotonic, now=lambda: datetime.now(timezone.utc),
                 build=build_site, push=push_site, template_dir=None):
        self._config = config
        self._assets_dir = assets_dir
        self._data_dir = data_dir
        self._clock = clock
        self._now = now
        self._build = build
        self._push = push
        self._template_dir = str(template_dir or default_template_dir())
        self._timeline = Timeline(data_dir)
        self._root = os.path.join(str(data_dir), "publish")
        self._next_due: float | None = None  # None: due now

    def tick(self) -> bool:
        """Keep the timeline current, then publish if the interval is up and the data
        changed. True if it published. The timeline runs every tick so its events are
        timed to the plugin's 30-second snapshots, not to the hourly publish."""
        self._timeline.update(self._now())
        if self._next_due is not None and self._clock() < self._next_due:
            return False
        return self.publish_if_changed()

    def publish_if_changed(self) -> bool:
        """Publish now if anything changed since the last successful publish."""
        try:
            with publish_lock(self._root) as held:
                if not held:
                    raise PublishError("another publish is in progress")
                state = self._fingerprint()
                if state == self._load_state():
                    self._next_due = self._clock() + self._interval_s
                    return False
                self._publish()
                self._save_state(state)
        except Exception as error:  # noqa: BLE001 - publishing must never stop the fog
            print(f"publish failed: {type(error).__name__}: {error}", flush=True)
            self._next_due = self._clock() + min(RETRY_S, self._interval_s)
            return False
        self._next_due = self._clock() + self._interval_s
        print(f"published to {self._config.remote} ({self._config.branch})", flush=True)
        return True

    @property
    def _interval_s(self) -> float:
        return self._config.interval_minutes * 60.0

    def _publish(self) -> None:
        staging = os.path.join(self._root, "staging")
        shutil.rmtree(staging, ignore_errors=True)
        self._build(self._assets_dir, self._data_dir, staging, self._now(),
                    template_dir=self._template_dir,
                    show_character_name=self._config.show_character_name,
                    mo2_profile=self._config.mo2_profile or None)
        self._push(
            staging_dir=staging,
            repo_dir=os.path.join(self._root, "repo.git"),
            remote=self._config.remote,
            branch=self._config.branch,
            author_name=self._config.author_name,
            author_email=self._config.author_email,
            git=self._config.git,
            leak_terms=None if self._config.leak_check else [],
        )

    def _fingerprint(self) -> list[str]:
        """Content hashes of everything the site is built from: the recorded data, the
        asset manifest (a rebuilt relief changes it) and the page itself, so an update
        to any of them reaches the published site.

        Contents rather than timestamps: the plugin rewrites markers.csv whether or not
        anything was discovered, which would otherwise publish every interval.
        """
        names = [f"path_{editor_id}.csv" for editor_id in load_manifest(self._assets_dir)]
        sources = [(name, os.path.join(str(self._data_dir), name))
                   for name in sorted(names) + ["markers.csv", "player.json", EVENTS_FILE]]
        sources.append((MANIFEST_NAME, os.path.join(str(self._assets_dir), MANIFEST_NAME)))
        if self._config.mo2_profile:
            sources.append(("modlist.txt", os.path.join(self._config.mo2_profile, "modlist.txt")))
        for folder, _, files in sorted(os.walk(self._template_dir)):
            for file in sorted(files):
                path = os.path.join(folder, file)
                sources.append((f"site/{os.path.relpath(path, self._template_dir)}", path))
        return [f"{label}:{_hash(path)}" for label, path in sources]

    def _load_state(self) -> list[str] | None:
        try:
            with open(os.path.join(self._root, "state.json"), "r", encoding="utf-8") as handle:
                return json.load(handle).get("fingerprint")
        except (OSError, ValueError, AttributeError):
            return None

    def _save_state(self, fingerprint: list[str]) -> None:
        os.makedirs(self._root, exist_ok=True)
        with open(os.path.join(self._root, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"fingerprint": fingerprint}, handle)


@contextlib.contextmanager
def publish_lock(root):
    """Yields True if this process now holds the publish lock, False if another does.

    A byte-range lock on a file, which the OS releases if the holder is killed -- as the
    companion is when the game closes -- so a dead publisher never wedges the next one.
    """
    os.makedirs(str(root), exist_ok=True)
    fd = os.open(os.path.join(str(root), "publish.lock"), os.O_RDWR | os.O_CREAT)
    try:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def _hash(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return "absent"


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")
