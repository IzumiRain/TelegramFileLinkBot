"""Self-updater: check GitHub for a newer commit and pull it.

The repo is private, so fetches authenticate with GITHUB_TOKEN from
.env when one is set. The token is only ever placed in the fetch URL
for the duration of that one git invocation — the saved remote
(`origin`) always keeps the clean, token-less URL.

Used from three places:
  * `python -m app.updater check|apply`  (update.sh wraps this)
  * the Telegram /update command (owners only)
  * the web admin panel's Update section

Updates are fast-forward only. If tracked files were modified locally
the update is refused (nothing is stashed or overwritten) — untracked
files such as .env and storage/ never block an update.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = "IzumiRain/TelegramFileLinkBot"
BRANCH = "main"


class Updater:
    def __init__(
        self,
        repo_dir: Path,
        github_token: str = "",
        repo_slug: str = DEFAULT_REPO,
        branch: str = BRANCH,
    ):
        self.repo_dir = Path(repo_dir)
        self.github_token = github_token.strip()
        self.repo_slug = repo_slug.strip() or DEFAULT_REPO
        self.branch = branch

    # -- git plumbing ------------------------------------------------------
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        return subprocess.run(
            ["git", "-C", str(self.repo_dir), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def _fetch_url(self) -> str:
        """URL to fetch from, with the token injected when available."""
        origin = self._git("config", "--get", "remote.origin.url")
        url = origin.stdout.strip() if origin.returncode == 0 else ""
        if not url:
            url = f"https://github.com/{self.repo_slug}.git"
        if self.github_token and "github.com" in url and "@" not in url:
            url = url.replace(
                "https://github.com/",
                f"https://x-access-token:{self.github_token}@github.com/",
                1,
            ).replace(
                "http://github.com/",
                f"https://x-access-token:{self.github_token}@github.com/",
                1,
            )
        return url

    def _is_repo(self) -> bool:
        return (
            self.repo_dir.is_dir()
            and self._git("rev-parse", "--git-dir").returncode == 0
        )

    def _head(self) -> str | None:
        result = self._git("rev-parse", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else None

    def _dirty_tracked(self) -> list[str]:
        result = self._git("status", "--porcelain", "--untracked-files=no")
        if result.returncode != 0:
            return []
        return [line[3:] for line in result.stdout.splitlines() if line.strip()]

    # -- public API ----------------------------------------------------------
    def status(self, fetch: bool = True) -> dict:
        """Current vs. remote state. Always returns a dict; on failure it
        carries an "error" key instead of raising."""
        if not self._is_repo():
            return {
                "ok": False,
                "error": f"{self.repo_dir} is not a git checkout — "
                "the updater needs the project cloned with git.",
            }
        current = self._head()
        info: dict = {
            "ok": True,
            "current": current,
            "current_short": (current or "")[:7],
            "branch": self.branch,
            "dirty": self._dirty_tracked(),
            "behind": None,
            "remote": None,
            "remote_short": None,
        }
        if not fetch:
            return info
        fetched = self._git("fetch", self._fetch_url(), self.branch)
        if fetched.returncode != 0:
            info["ok"] = False
            info["error"] = (
                "git fetch failed: "
                + (fetched.stderr or fetched.stdout).strip()[-400:]
            )
            return info
        remote = self._git("rev-parse", "FETCH_HEAD").stdout.strip()
        info["remote"] = remote
        info["remote_short"] = remote[:7]
        behind = self._git("rev-list", "--count", f"HEAD..{remote}")
        ahead = self._git("rev-list", "--count", f"{remote}..HEAD")
        info["behind"] = int(behind.stdout.strip() or 0)
        info["ahead"] = int(ahead.stdout.strip() or 0)
        info["up_to_date"] = info["behind"] == 0
        return info

    def apply(self) -> dict:
        """Fetch and fast-forward to the remote commit, reinstalling
        dependencies when requirements.txt changed. Returns a report
        dict with a human-readable "log" list."""
        log: list[str] = []
        before = self.status(fetch=True)
        if not before.get("ok"):
            return {"ok": False, "error": before.get("error", "status failed"), "log": log}
        if before["behind"] == 0:
            return {
                "ok": True,
                "updated": False,
                "current": before["current"],
                "log": [f"Already up to date ({before['current_short']})."],
            }
        if before["dirty"]:
            return {
                "ok": False,
                "error": "Local changes to tracked files would be overwritten: "
                + ", ".join(before["dirty"])
                + ". Commit/stash them or re-clone, then update.",
                "log": log,
            }
        old = before["current"]
        remote = before["remote"]
        log.append(
            f"Updating {before['current_short']} → {before['remote_short']} "
            f"({before['behind']} new commit(s))…"
        )
        merged = self._git("merge", "--ff-only", remote)
        if merged.returncode != 0:
            return {
                "ok": False,
                "error": "git merge --ff-only failed: "
                + (merged.stderr or merged.stdout).strip()[-400:],
                "log": log,
            }
        changed = self._git(
            "diff", "--name-only", f"{old}..{remote}"
        ).stdout.split()
        log.append("Updated. Changed files: " + (", ".join(changed) or "—"))
        deps_updated = False
        if "requirements.txt" in changed:
            log.append("requirements.txt changed — reinstalling dependencies…")
            pip = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if pip.returncode != 0:
                return {
                    "ok": False,
                    "error": "pip install failed: "
                    + (pip.stderr or pip.stdout).strip()[-400:],
                    "log": log,
                }
            deps_updated = True
            log.append("Dependencies reinstalled.")
        return {
            "ok": True,
            "updated": True,
            "current": remote,
            "deps_updated": deps_updated,
            "restart_required": True,
            "log": log,
        }


def _from_env() -> Updater:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    root = Path(__file__).resolve().parent.parent
    return Updater(
        repo_dir=root,
        github_token=os.getenv("GITHUB_TOKEN", ""),
        repo_slug=os.getenv("GITHUB_REPO", DEFAULT_REPO),
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "check"
    updater = _from_env()
    if command == "check":
        info = updater.status(fetch=True)
        if not info.get("ok"):
            print(f"[update] ERROR: {info.get('error')}")
            return 1
        if info["up_to_date"]:
            print(f"[update] Up to date ({info['current_short']}).")
            return 0
        print(
            f"[update] Update available: {info['current_short']} → "
            f"{info['remote_short']} ({info['behind']} new commit(s)). "
            "Run: bash update.sh apply"
        )
        return 3
    if command == "apply":
        report = updater.apply()
        for line in report.get("log", []):
            print(f"[update] {line}")
        if not report.get("ok"):
            print(f"[update] ERROR: {report.get('error')}")
            return 1
        if report.get("updated"):
            print("[update] Done. Restart the bot to run the new code.")
        return 0
    print("Usage: python -m app.updater [check|apply]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
