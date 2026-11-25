"""Classify durable job state for safe startup and takeover.

Safety is not inferred from an empty *partial* list. A job is only terminal when
its solver and (where the mode has one) extraction stages have positively
finished and no worker still owns it. Anything inconsistent, stale or unresolved
is ``uncertain`` and blocks takeover just like active work.
"""

from __future__ import annotations

import time

ACTIVE = "active"
UNCERTAIN = "uncertain"
TERMINAL = "terminal"

STALE_SECONDS = 30

ACTIVE_SOLVER = {"Queued", "Preparing", "Running", "Waiting for license"}
ACTIVE_EXTRACTION = {"Queued", "Running"}
TERMINAL_STAGE = {"Succeeded", "Failed", "Cancelled"}


def classify(job, now=None):
    """Return ``active``, ``uncertain`` or ``terminal`` for one job row."""
    now = time.time() if now is None else now
    solver = job.get("solver") or "Queued"
    extraction = job.get("extraction") or "Pending"
    phase = job.get("phase") or ""
    owner = job.get("owner")
    heartbeat = job.get("heartbeat")
    cancelled = bool(job.get("cancelled"))

    if phase == "Process termination unconfirmed":
        return UNCERTAIN
    if job.get("status") in {"Unknown / worker disconnected", "Cancel requested"}:
        return UNCERTAIN
    if owner:
        if heartbeat is None or now - float(heartbeat) > STALE_SECONDS:
            return UNCERTAIN
        if cancelled:
            return UNCERTAIN
    if solver in ACTIVE_SOLVER:
        return ACTIVE
    if solver == "Succeeded":
        if extraction in ACTIVE_EXTRACTION:
            return ACTIVE
        if extraction in TERMINAL_STAGE:
            return UNCERTAIN if owner else TERMINAL
        # A completed solver with a pending/unknown extraction is inconsistent;
        # do not treat it as safe inactivity.
        return UNCERTAIN
    if solver in {"Failed", "Cancelled"}:
        # A failed or cancelled solver may still have a queued/running extraction:
        # that is real work on a stopped process, not an unresolved analysis.
        if extraction in ACTIVE_EXTRACTION:
            return ACTIVE
        return UNCERTAIN if owner else TERMINAL
    return UNCERTAIN


def summary(jobs, now=None):
    """Counts by class, for diagnostics output."""
    counts = {ACTIVE: 0, UNCERTAIN: 0, TERMINAL: 0}
    for job in jobs:
        counts[classify(job, now)] += 1
    return counts
