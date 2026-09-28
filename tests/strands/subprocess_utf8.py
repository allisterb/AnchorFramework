"""Text crosses every subprocess boundary as UTF-8, on every platform.

    python tests/strands/subprocess_utf8.py

Anchor chains three runtimes through pipes: Python calls `dogwood` (Rust), other Python programs
(the checker), and Java (TLC and SANY). All of them write UTF-8 where it matters -- dogwood draws its
diagnostics with box characters -- but a pipe's text is decoded with the LOCALE, and on Windows the
locale is cp1252. That was invisible on Linux, and so in CI and the container, and on Windows it
did three different things:

    dogwood's diagnostic           came back as mojibake ('\\u00c3\\u2014' for a multiplication sign)
    relayed through the checker     crashed a reader thread on byte 0x9d, and the text was LOST
    a non-ASCII string in TLA+      was read as cp1252 by the JVM and printed back mangled

The second is the one that matters: a failure that reads as an absence of output. Each is pinned
here against the real programs, not a mock -- the point is the bytes that actually cross.

THIS FILE IS PLAIN ASCII, and so is everything it prints: every non-ASCII character below is an
escape. The C# wrapper reads this script's own output with the platform's default encoding, and a
test about encodings should not depend on the one it is testing.
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "src", REPO / "src" / "agent"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from checker import engine  # noqa: E402
from translator import tlc  # noqa: E402
import invoke  # noqa: E402

BROKEN = REPO / "tests" / "policies" / "syntax_broken.dw"

# What dogwood draws a diagnostic with: rounded corner, horizontal, vertical, arrowhead, times.
BOX = ("\u256d", "\u2500", "\u2502", "\u25b6", "\u00d7")

# The same characters after a UTF-8 -> cp1252 round trip: the leading bytes 0xC3 and 0xE2 decode
# as these, followed by the pieces cp1252 makes of the continuation bytes.
MOJIBAKE = ("\u00c3", "\u00e2\u2022", "\u00e2\u201d", "\u00e2\u2013")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{('  -- ' + ascii(detail)[:200]) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    if not engine.available():
        print(f"SKIPPED: no dogwood binary at {engine.DOGWOOD}. Build it with\n"
              f"    cargo build --release --locked --manifest-path ext/dogwood/Cargo.toml")
        return 0

    # --- dogwood -> Python --------------------------------------------------------------------------
    parsed = engine.check_parse(BROKEN)
    out = parsed["output"]
    check("dogwood ran, and refused the file", parsed["ran"] and not parsed["ok"], str(parsed))
    check("its diagnostic arrives with the box characters it was drawn with",
          any(c in out for c in BOX), out)
    check("and without mojibake", not any(m in out for m in MOJIBAKE), out)

    # --- dogwood -> the checker -> Python ------------------------------------------------------------
    # The path audit.py and the pipeline take: a Python child relaying what dogwood said. This is the
    # one that LOST the text -- the child's reader thread died on 0x9d and the stream came back empty.
    relayed = invoke.checker([str(BROKEN), "--syntax"], timeout=300)
    text = (relayed.stdout or "") + (relayed.stderr or "")
    check("the checker exits 2 for a file that does not parse", relayed.returncode == 2,
          f"exit {relayed.returncode}: {text}")
    check("the relayed diagnostic survives two pipes", "unexpected token" in text, text)
    check("with its box characters", any(c in text for c in BOX), text)
    check("and without mojibake", not any(m in text for m in MOJIBAKE), text)
    check("and nothing crashed on the way", "Traceback" not in text and "UnicodeDecodeError" not in text,
          text)

    # --- Python -> Java -> Python --------------------------------------------------------------------
    # Both directions at once: the JVM has to READ the module as UTF-8 and WRITE the value back as
    # UTF-8, and we have to decode it as UTF-8. Any one of the three wrong and this comes back mangled.
    # LATIN-1 ONLY, and that is TLA+'s rule rather than ours: SANY rejects an em dash inside a string
    # literal as a lexical error. Every character here is still two bytes in UTF-8, which is all the
    # test needs.
    word = "h\u00e9llo, na\u00efve, \u00fcber"
    with tempfile.TemporaryDirectory(prefix="anchor-utf8-") as scratch:
        ok, value = tlc.run_eval(f'"{word}"', "Naturals", Path(scratch), spec=None)
    check("TLC evaluates a non-ASCII string", ok, value)
    check("and hands it back exactly", value == f'"{word}"', value)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed.")
        return 1
    print("text crosses every subprocess boundary as UTF-8: dogwood, the checker and TLC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
