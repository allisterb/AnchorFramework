"""One checker invocation, and the memo on it.

THE CHECKER IS A PURE FUNCTION and it is expensive, which is the whole case for this file. Its
answer depends on its argv and on the bytes of the files that argv names -- there is no randomness
anywhere in it (mutants are enumerated, not sampled), and five modes were run twice and compared to
confirm it rather than assumed. What it costs is a JVM: **about 1.6s of the ~2.0s a minimal TLC run
takes is starting one**, measured on a one-state model, so the price is paid per invocation almost
regardless of what is being checked.

AND THE PIPELINE ASKS THE SAME QUESTION SEVERAL TIMES, in three places that are all natural rather
than careless:

    the derived questions depend on the POLICY ALONE.    `stage_check` runs them per attempt, so a
                                                        `hitl` session of four attempts asks the
                                                        identical question four times, and a sweep
                                                        of five requirements against one policy
                                                        asks it five times. ~10s each.

    `stage_draft` probes the property it just drafted    ...and `stage_check` then checks the same
    to find out whether its claims evaluate at all       module against the same policy. Identical
                                                        argv, identical bytes.

    `describe` is read per attempt                       and the policy has not changed.

Measured over the four slowest harnesses: `pipeline_run` 213s -> 134s, `property_authoring` 47s ->
33s, `hitl_loop` 83s -> 62s, `repair_loop` 62s -> 54s. The suite's serial work is ~80% JVM startup,
and this is the only lever on it that does not delete a check -- **nothing here changes what is
asked or what comes back**, which is why it is a memo and not a smaller set of questions.

TWO THINGS IT WILL NOT DO.

    `--keep` IS NEVER CACHED.  Without it the checker writes into a temp directory that is deleted
                               when it exits, so stdout and the exit code are the whole of its
                               observable output. With it the model, the `.cfg` and the raw TLC
                               output are written to a directory the caller reads afterwards --
                               and replaying that from memory would leave the directory unwritten,
                               or worse, stale from an earlier run. `audit.py` passes it.

    IT DOES NOT OUTLIVE THE PROCESS.  No disk cache. A stale answer that survives a checker change
                               is a verification tool reporting a verdict about code that no longer
                               exists, and no amount of key hygiene is worth that risk against a
                               saving measured in seconds.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CHECKER = REPO / "src" / "checker" / "properties.py"

# Bounded, because an entry holds a whole TLC transcript and a long sweep makes hundreds of calls.
# The reuse this exists for is always within one policy's run or one session, so a small window
# catches all of it; a larger one would only hold onto answers nothing is going to ask for again.
LIMIT = 64

_memo: OrderedDict[str, subprocess.CompletedProcess[str]] = OrderedDict()

# What it saved, for anything that wants to report honestly on what actually ran.
ran = 0
reused = 0


def enabled() -> bool:
    """Off with `ANCHOR_CHECKER_MEMO=0` — the switch to reach for when a verdict looks impossible."""
    return os.environ.get("ANCHOR_CHECKER_MEMO", "1") not in ("0", "false", "no")


def fingerprint(cmd: list[str]) -> str | None:
    """argv, plus the content of every argument that names a file. `None` = do not cache.

    CONTENT AND NOT mtime, because the thing most likely to change between two calls is a drafted
    module rewritten to the SAME PATH on the next round -- which is exactly the case an mtime key
    would get right only by luck and a path-only key would get wrong every time.
    """
    if "--keep" in cmd:
        return None

    h = hashlib.sha256()
    for part in cmd:
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
        try:
            f = Path(part)
            if f.is_file():
                h.update(f.read_bytes())
        except OSError:
            # Unreadable, or not a path at all. The argv text is already in the key, and a call
            # whose input cannot be read is one the checker is about to complain about anyway.
            pass
    return h.hexdigest()


def checker(args: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    """Run `properties.py` with these arguments, from the repo root. Repeats are free."""
    global ran, reused

    cmd = [sys.executable, str(CHECKER), *args]
    key = fingerprint(cmd) if enabled() else None

    if key is not None and (hit := _memo.get(key)) is not None:
        _memo.move_to_end(key)
        reused += 1
        return hit

    # UTF-8 both ways: PYTHONUTF8 makes the child WRITE it, and the encoding makes us READ it.
    # Either half alone breaks on Windows, whose locale default is cp1252.
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONUTF8": "1"}, timeout=timeout)
    ran += 1

    # A TIMEOUT IS NOT CACHED, because `subprocess.run` raises rather than returning and there is
    # nothing to remember. That is the right behaviour: a run that was cut off says nothing about
    # what the answer would have been.
    if key is not None:
        _memo[key] = proc
        while len(_memo) > LIMIT:
            _memo.popitem(last=False)
    return proc


def clear() -> None:
    """Forget everything, and the counters with it."""
    global ran, reused
    _memo.clear()
    ran = reused = 0
