"""`src/translator/tlc.py`: a JVM the checker starts must die with the checker.

IT DID NOT. On a timeout `PythonProcess` kills the checker's process tree, but on Windows the venv's
`python.exe` is a launcher whose child is the real interpreter. .NET kills the root first; the
launcher's job takes the interpreter with it at once; and when .NET then looks for the interpreter's
children, there is no interpreter left to look under. One TLC run on aws1's 12-rule policy set kept a
core and 2.7 GB for fifteen hours after the CLI had reported the timeout.

`bound_popen` puts the JVM in a job that Windows kills when the checker's process ends, however it
ends. Checked here the way it failed: a venv-launched Python starts a child and is then terminated
from outside, as `Process.Kill` does.

  1. THE CONTROL, without which the rest proves nothing: a plain `subprocess.Popen` child SURVIVES
     its interpreter being terminated. If it did not, this harness could not see the bug.
  2. A `bound_popen` child does not.

`ping` stands in for java: what is under test is the binding, not the JVM, and ping costs nothing.

Windows only. Elsewhere the venv's python is the interpreter itself, the tree kill reaches java, and
`bound_popen` binds nothing; the harness says SKIPPED.

    python/Scripts/python.exe tests/strands/tlc_lifetime.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VENV_PYTHON = REPO / "python" / "Scripts" / "python.exe"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)
        if detail:
            print(f"          {detail[:400]}")


# The child: start ping one way or the other, say its pid, and wait. Run under the VENV LAUNCHER,
# because that is the process tree the bug needs.
CHILD = """
import subprocess, sys
sys.path.insert(0, {src!r})
cmd = ["ping", "-n", "120", "127.0.0.1"]
if sys.argv[1] == "bound":
    from translator.tlc import bound_popen
    p = bound_popen(cmd, ".")
else:
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
p.wait()
"""


def alive(pid: int) -> bool:
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
    if not handle:
        return False
    try:
        return k32.WaitForSingleObject(handle, 0) == 0x102      # WAIT_TIMEOUT: still running
    finally:
        k32.CloseHandle(handle)


def survives(mode: str) -> tuple[bool, int]:
    """Start the child under the venv launcher, terminate the launcher, and report on ping."""
    launcher = subprocess.Popen([str(VENV_PYTHON), "-c", CHILD.format(src=str(REPO / "src")), mode],
                                stdout=subprocess.PIPE, text=True)
    pid = int(launcher.stdout.readline())
    launcher.kill()                                 # TerminateProcess, as Process.Kill does
    launcher.wait()
    time.sleep(2)
    left = alive(pid)
    if left:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    return left, pid


def main() -> int:
    if sys.platform != "win32":
        print("SKIPPED: Windows only -- elsewhere the venv's python is the interpreter itself")
        return 0
    if not VENV_PYTHON.exists():
        print(f"SKIPPED: no venv launcher at {VENV_PYTHON}")
        return 0

    print("A child of the checker, after the checker is terminated")
    print("-" * 78)
    left, pid = survives("plain")
    check("the control: a plain Popen child outlives its venv-launched interpreter", left,
          f"ping {pid} died with it, so this harness cannot see the bug it exists for")
    left, pid = survives("bound")
    check("a bound_popen child dies with it", not left, f"ping {pid} was still running")

    print()
    print("all checks passed" if not failures else f"{len(failures)} FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
