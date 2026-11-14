"""One active job per user — the registry behind /stop.

Long operations (a big Telegram download, a slow URL download, an
upload) run as the handler's own asyncio task. Registering that task
under the user's ID lets the /stop command find and cancel it, and
lets new requests see that the user already has something running.
"""
from __future__ import annotations

import asyncio

_KEY = "active_jobs"


def _jobs(bot_data: dict) -> dict:
    return bot_data.setdefault(_KEY, {})


def begin_job(bot_data: dict, user_id: int) -> asyncio.Task | None:
    """Register the current task as `user_id`'s active job.

    Returns the task, or None when the user already has a job running
    (in that case nothing is registered)."""
    jobs = _jobs(bot_data)
    current = jobs.get(user_id)
    if current is not None and not current.done():
        return None
    task = asyncio.current_task()
    jobs[user_id] = task
    return task


def end_job(bot_data: dict, user_id: int, task: asyncio.Task | None) -> None:
    """Unregister `task` if it is still the user's active job."""
    jobs = _jobs(bot_data)
    if task is not None and jobs.get(user_id) is task:
        jobs.pop(user_id, None)


def active_job(bot_data: dict, user_id: int) -> asyncio.Task | None:
    task = _jobs(bot_data).get(user_id)
    if task is not None and not task.done():
        return task
    return None


def cancel_job(bot_data: dict, user_id: int) -> bool:
    """Cancel the user's active job. True when there was one."""
    task = active_job(bot_data, user_id)
    if task is None:
        return False
    task.cancel()
    return True
