"""The reference engine, asked the questions only it can answer.

`dogwood` is the Dogwood language's own CLI. Anchor does not need it to work -- everything here
degrades to "not available" and says so -- but where it is present it settles two questions that
our own parser cannot settle about itself:

    IS THIS EVEN A DOGWOOD POLICY?   Our parser reads a SUBSET, so it has two ways to fail and one
                                     message for both. `expected '::', got '{'` means either "this
                                     construct is outside the subset" or "this policy is broken",
                                     and those need opposite responses: one is our limitation to
                                     work around, the other is a bug in the file to go and fix.

    WHERE IS THE ERROR?              The engine answers with a miette source snippet pointing at
                                     the offending token. Our parser knows a token index.

THIS IS NOT A VERIFICATION FINDING and must never be reported as one. A policy that does not parse
has not been checked, and saying so is the whole point -- see `properties.py`, where a syntax error
exits 2 (no verdict) rather than 0.

It costs about 35ms, which is why the refusal path takes it unconditionally: by then the run has
already failed, and 35ms is nothing against telling somebody the wrong thing about why.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Not in the repo -- it is built from the pinned submodule. Absence is an ordinary state here, not
# an error, because every caller has something useful to do without it.
#     cargo build --release --locked --manifest-path ext/dogwood/Cargo.toml
#
# ANCHOR_DOGWOOD names it somewhere else, which is how the container image says where it put the
# binary. An image has no submodule and no cargo target directory, and recreating that path inside
# one purely so this constant resolves would be a lie the next reader has to decode. Same reason
# ANCHOR_ROOT and ANCHOR_CLI exist.
DOGWOOD = (Path(os.environ["ANCHOR_DOGWOOD"]) if os.environ.get("ANCHOR_DOGWOOD") else
           REPO / "ext" / "dogwood" / "target" / "release"
           / ("dogwood.exe" if sys.platform == "win32" else "dogwood"))

BUILD_IT = ("build it with:\n"
            "    cargo build --release --locked --manifest-path ext/dogwood/Cargo.toml")


def available(dogwood: Path = DOGWOOD) -> bool:
    return dogwood.exists()


def check_parse(policy: Path, *, dogwood: Path = DOGWOOD, timeout: int = 60) -> dict:
    """Does the reference implementation parse this file?

    Returns `{"ran": bool, "ok": bool, "output": str}`. `ran` false means the binary was not there
    or could not be started, which is NOT a statement about the policy -- conflating "we could not
    ask" with "it is broken" would be the same mistake this module exists to prevent.

    SYNTAX AND MACROS ONLY. `check-parse` does not type-check against a schema; `dogwood validate`
    does, and needs one. A file that passes here can still be rejected at deployment.
    """
    if not dogwood.exists():
        return {"ran": False, "ok": False,
                "output": f"no dogwood binary at {_short(dogwood)} -- {BUILD_IT}"}
    try:
        # UTF-8, stated: dogwood is Rust and writes UTF-8 -- its diagnostics draw boxes and arrows
        # -- while `text=True` alone decodes with the locale, cp1252 on Windows. That returned
        # mojibake, and on a byte cp1252 has no mapping for, lost the diagnostic entirely.
        proc = subprocess.run([str(dogwood), "check-parse", str(policy)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ran": False, "ok": False, "output": f"could not run {_short(dogwood)}: {e}"}

    return {"ran": True, "ok": proc.returncode == 0,
            "output": (proc.stdout + proc.stderr).strip()}


def explain_refusal(policy: Path, *, dogwood: Path = DOGWOOD) -> str:
    """Extra lines to print beside OUR refusal, once we have already decided to refuse.

    The distinction it draws is the one a reader most needs and cannot make: whether the construct
    we would not model is a construct at all. Silent when the engine agrees the file is fine --
    then our refusal stands on its own and a second opinion would only be noise.
    """
    if not dogwood.exists():
        return ""

    result = check_parse(policy, dogwood=dogwood)
    if not result["ran"] or result["ok"]:
        return ""

    return ("\nAND IT IS NOT VALID DOGWOOD EITHER. The reference implementation refuses to parse\n"
            "this file, so the refusal above is not a limit of the modelled subset -- there is a\n"
            "syntax error in the policy. `dogwood check-parse` says:\n\n"
            + "\n".join(f"    {line}" for line in result["output"].splitlines()[:18]))


def _short(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)
