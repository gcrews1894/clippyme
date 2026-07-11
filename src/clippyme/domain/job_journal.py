"""Minimal on-disk journal for the in-memory job queue.

The ``jobs`` dict and ``asyncio.Queue`` live only in memory, so a backend
restart used to silently lose every queued job and orphan the subprocess of
every processing one. This module persists just enough state to recover:

* ``snapshot``/``save_journal`` — one atomic JSON file (``data/jobs_journal.json``)
  holding the ACTIVE jobs only ({status, cmd, output_dir, pid, updated_at}).
  NEVER the env (it carries the Gemini API key), the Popen handle, logs or
  results. ``data/`` is deliberately chosen over ``output/<job_id>/``: the
  output tree is served by the ``/videos`` static mount and is rmtree'd by
  cancel, so a per-job state file there would be publicly downloadable and
  could be deleted out from under its own record.
* ``make_journal_writer`` — the ``on_change`` hook threaded into
  ``submit_job``/``make_run_job``/the control handlers. Swallows + logs I/O
  errors so journalling can never break a request.
* ``plan_recovery`` (pure) + ``recover_jobs`` — startup path: ``queued``
  entries are re-enqueued; ``processing``/``paused`` entries are checked
  against the disk first (a job killed between its final render and the
  journal prune is restored as ``completed``) and otherwise marked ``failed``
  with a clear log line. ``failed`` is reused instead of a new status because
  the frontend poller only terminates on completed|stopped|cancelled|failed —
  an unknown status would poll forever.
* ``kill_stale_tree`` — best-effort psutil kill of an orphaned pipeline tree
  from a previous server life, guarded by an argv prefix match so a recycled
  pid can never kill an unrelated process. No re-adoption: the Popen handle
  is gone, so the safe move is to kill and let the user resubmit.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field

from clippyme.domain.job_control import ACTIVE_STATES

logger = logging.getLogger("clippyme")

JOURNAL_FILENAME = "jobs_journal.json"


def snapshot(jobs: dict) -> dict:
    """Journal records for every ACTIVE job. Secrets (env), live handles
    (process), logs and results are deliberately excluded."""
    records = {}
    for job_id, job in jobs.items():
        status = job.get("status")
        if status not in ACTIVE_STATES:
            continue
        records[job_id] = {
            "status": status,
            "cmd": list(job.get("cmd") or []),
            "output_dir": job.get("output_dir", ""),
            "pid": job.get("pid"),
            "updated_at": time.time(),
        }
    return records


def save_journal(path: str, records: dict) -> None:
    """Atomic write (tmp + os.replace, 0o600 — same pattern as job_artifacts)."""
    tmp_path = path + ".tmp"
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def load_journal(path: str) -> dict:
    """Read the journal; {} on missing or corrupt file (logged, never raises)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Job journal unreadable (%s) — starting empty: %s", path, exc)
        return {}


def make_journal_writer(*, jobs: dict, path: str):
    """The ``on_change`` hook: snapshot + save, swallowing I/O errors."""

    def persist() -> None:
        try:
            save_journal(path, snapshot(jobs))
        except Exception as exc:
            logger.warning("Could not persist job journal: %s", exc)

    return persist


@dataclass
class RecoveryPlan:
    requeue: list = field(default_factory=list)       # [(job_id, record)]
    mark_failed: list = field(default_factory=list)   # [(job_id, record)]


def plan_recovery(records: dict) -> RecoveryPlan:
    """Pure classification of journal records found at startup."""
    plan = RecoveryPlan()
    for job_id, record in records.items():
        status = (record or {}).get("status")
        if status == "queued":
            plan.requeue.append((job_id, record))
        elif status in ("processing", "paused"):
            plan.mark_failed.append((job_id, record))
    return plan


def kill_stale_tree(pid, expected_cmd) -> bool:
    """Kill the process tree at ``pid`` iff its argv still matches the job's
    recorded cmd prefix (guards against pid reuse). Best-effort; returns
    whether a kill was attempted."""
    if not pid:
        return False
    try:
        import psutil

        proc = psutil.Process(int(pid))
        cmdline = proc.cmdline()
        expected = [str(c) for c in (expected_cmd or [])][:2]
        if not expected or cmdline[: len(expected)] != expected:
            return False
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        proc.kill()
        return True
    except Exception:
        return False


def recover_jobs(*, journal_path: str, jobs: dict, job_queue, output_root: str) -> dict:
    """Startup recovery. Mutates ``jobs``/``job_queue`` in place and rewrites
    the journal to reflect the recovered state. Returns counts for logging.

    A ``processing`` job whose final result actually made it to disk (killed
    between render-finish and journal-prune) is restored as ``completed``
    instead of being failed.
    """
    from clippyme.domain.clip_endpoints import restore_job_from_disk
    from clippyme.domain.errors import ClippyMeError
    from clippyme.domain.job_results import load_final_result

    plan = plan_recovery(load_journal(journal_path))
    counts = {"requeued": 0, "failed": 0, "restored": 0}

    for job_id, record in plan.requeue:
        entry = {
            "status": "queued",
            "logs": ["Re-enqueued after server restart."],
            "cmd": record.get("cmd") or [],
            # Header-supplied keys (X-Gemini-Key) are not recoverable — the
            # run-time persistent-config merge in run_job fills missing ones.
            "env": os.environ.copy(),
            "output_dir": record.get("output_dir", ""),
        }
        try:
            jobs[job_id] = entry
            job_queue.put_nowait(job_id)
            counts["requeued"] += 1
        except Exception as exc:
            jobs.pop(job_id, None)
            logger.warning("Could not re-enqueue job %s after restart: %s", job_id, exc)

    for job_id, record in plan.mark_failed:
        output_dir = record.get("output_dir", "")
        final = None
        try:
            final = load_final_result(job_id, output_dir)
        except Exception:
            final = None
        if final:
            try:
                jobs[job_id] = restore_job_from_disk(
                    job_id, output_root, os.path.join(output_root, job_id))
                counts["restored"] += 1
                continue
            except ClippyMeError:
                pass
        if kill_stale_tree(record.get("pid"), record.get("cmd")):
            logger.info("Killed orphaned pipeline tree for interrupted job %s (pid=%s)",
                        job_id, record.get("pid"))
        jobs[job_id] = {
            "status": "failed",
            "logs": ["Job interrupted by server restart."],
            "cmd": record.get("cmd") or [],
            "env": {},
            "output_dir": output_dir,
        }
        counts["failed"] += 1

    try:
        save_journal(journal_path, snapshot(jobs))
    except Exception as exc:
        logger.warning("Could not rewrite job journal after recovery: %s", exc)

    if any(counts.values()):
        logger.info("Job recovery: %d re-enqueued, %d restored from disk, %d marked failed",
                    counts["requeued"], counts["restored"], counts["failed"])
    return counts
