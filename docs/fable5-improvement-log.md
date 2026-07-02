# Fable 5 improvement log

Running log of the audit-driven improvement waves (2026-07-02 →). One entry per
improvement: what changed, why it mattered, verification evidence. The full
ranked audit lives in the session that produced this plan; each wave below maps
to an approved audit finding.

## Wave 1 — backend correctness (2026-07-02)

**1. `/api/cancel` race vs natural completion (High).**
`app.py:cancel_job` now refuses (HTTP 409) when the job's subprocess has
already exited: `run_job`'s 2s poll loop may not have observed the exit yet, so
the status still reads `processing` — honouring the cancel in that window
`rmtree`'d a fully-rendered job. Queued jobs (no process handle) stay
cancellable via the existing pre-dispatch guard.
Test: `tests/api/test_job_controls.py::test_cancel_refused_when_process_already_exited`
(+ `test_cancel_kills_running_process`, `test_cancel_queued_job_still_allowed`).

**2. Orphaned subprocess on unexpected `run_job` exception (High).**
An exception escaping the poll loop (e.g. a `TypeError` from a result loader)
set status `failed` but left the pipeline subprocess running — unkillable via
the API (`can_cancel('failed')` is False) while its concurrency slot was
already released. The `except` branch now kills any still-alive process.
Test: `tests/api/test_job_controls.py::test_run_job_kills_orphan_on_unexpected_error`.

**3. Missing ffmpeg timeouts on compose layers (High).**
`grade.py` / `hooks.py` / `logo.py` / `subtitles.py` ran ffmpeg with no
`timeout=`; each call executes on asyncio's shared default thread pool, so a
few hung ffmpeg processes would pin its workers and stall job polling
server-wide. All four now pass `encode.ffmpeg_timeout()` (new,
`CLIPPYME_FFMPEG_TIMEOUT`, default 600s). Grade degrades to
keep-ungraded-input on timeout; hook/logo raise with a clear message.
`logo.py`'s ffprobe also gained a 30s timeout and a warning log on its
previously-silent 1080×1920 fallback (wrong for 1:1 / 16:9 jobs).
Tests: `tests/domain/test_encode.py::test_ffmpeg_timeout_default_and_env`,
`tests/domain/test_grade.py::test_apply_grade_timeout_returns_false`.

**4. Log-reader thread died on non-UTF-8 bytes (Med-High).**
`job_worker.enqueue_output` decoded subprocess output with strict UTF-8; one
stray byte (ffmpeg/yt-dlp) raised, the outer except ended the read loop, and
the job's visible log froze for the rest of the run. Now decodes with
`errors="replace"`.
Test: `tests/domain/test_job_worker.py` (new file, 5 cases).

**5. Retention sweep could purge an active job (Med).**
`cleanup_jobs` purged by directory mtime only; a long-paused/slow job whose
dir gained no new entries within `JOB_RETENTION_SECONDS` was purge-eligible
while its subprocess was alive. New pure guard `job_control.can_purge(status)`
skips jobs in `ACTIVE_STATES`. Cleanup-failure logs bumped `debug`→`warning`
(the app's INFO basicConfig made them invisible — a systematically failing
cleanup was a silent disk leak).
Test: `tests/pipeline/test_job_control.py::test_can_purge_blocks_active_jobs`.

**6. Secret-scan hook missed ElevenLabs keys (Med).**
`.githooks/pre-commit`: added `sk_[a-f0-9]{20,}` (ElevenLabs uses `sk_`, which
the OpenAI `sk-` pattern never matched), added `ELEVENLABS` to the name-based
alternation, and allowed optional quotes around name/value so JSON-style
`"X_API_KEY": "…"` lines are caught for every provider.
Verified by piping 4 representative fake-key samples through the exact
patterns (all matched).

**Verification (Wave 1):** `pytest -m "not integration"` → 583 passed,
3 skipped. `ruff check src/clippyme tests --select E9,F63,F7,F82` (CI rule
set) → clean. Commit `6749f0e`.

## Wave 2 — per-clip serialisation locks (2026-07-02)

**7. Concurrent reframe/compose on the same clip raced deterministic files
(Med-High).** New `domain/clip_locks.py`: a refcounted `asyncio.Lock` registry
keyed `(job_dir, clip_index)` (async analogue of `smartcut._CLIP_LOCKS`).
`compose_layers` acquires it around the whole layer pipeline (covers both
`/api/compose` and publish's `compose_first`); `/api/reframe` acquires the
same lock around the `--reframe-only` subprocess + metadata write. Before: a
double-clicked "Apply & reprocess" spawned two subprocesses racing
`os.replace` on the same `<clip>.reframe.tmp.mp4`, both returning success over
a nondeterministic result; an overlapping Download + Publish could delete the
other's in-flight `composed_*_{i}.mp4`. Different clips remain fully parallel.
Tests: `tests/domain/test_clip_locks.py` (mutual exclusion, cross-clip
parallelism via event-handshake, registry cleanup, path normalisation).

**Verification (Wave 2):** `pytest -m "not integration"` → 587 passed,
3 skipped. CI ruff rule set → clean.
