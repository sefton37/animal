"""The sandbox. Runs a command as an argv vector (never a shell string) with the
strongest confinement the host allows, and RECORDS which mode it got — honesty
about degradation is the point (a silently-weaker sandbox is the trap).

Modes, probed at startup:
  full     bwrap: root read-only, workspace writable, network off (--unshare-net)
  fs_only  bwrap: root read-only, workspace writable, network NOT isolated
  degraded no usable bwrap userns (e.g. nested container): run with cwd=workspace
           and a scrubbed env; control-plane protection falls to the tool layer.

On the real Corellia box this probes to `full`. Inside the nested build/test
environment it degrades — and says so in every envelope + the ledger.
"""
from __future__ import annotations
import subprocess, shutil, os
from pathlib import Path

_BASE = ["--unshare-user", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]


class Sandbox:
    def __init__(self):
        self.mode = self._probe()

    def _probe(self) -> str:
        if not shutil.which("bwrap"):
            return "degraded"
        for mode, extra in (("full", ["--unshare-net"]), ("fs_only", [])):
            try:
                r = subprocess.run(["bwrap", *_BASE, *extra, "--chdir", "/tmp", "--", "/usr/bin/true"],
                                   capture_output=True, timeout=10)
                if r.returncode == 0:
                    return mode
            except Exception:
                pass
        return "degraded"

    def run(self, argv: list[str], workspace, timeout: int = 120) -> dict:
        """Execute argv in the workspace. Returns a computed result dict (real exit
        code, captured output, and the sandbox mode actually used)."""
        ws = str(Path(workspace).resolve())
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": ws,
               "LANG": "C.UTF-8", "TMPDIR": "/tmp",
               # checks are ephemeral: never leave a bytecode cache that could
               # poison a later run's result (reproducibility hygiene)
               "PYTHONDONTWRITEBYTECODE": "1"}
        if self.mode in ("full", "fs_only"):
            net = ["--unshare-net"] if self.mode == "full" else []
            cmd = ["bwrap", *_BASE, "--bind", ws, ws, *net, "--chdir", ws, "--", *argv]
            run_cwd = None                      # bwrap sets --chdir
        else:
            cmd = list(argv)                    # degraded: plain subprocess in the workspace
            run_cwd = ws
        try:
            r = subprocess.run(cmd, cwd=run_cwd, env=env, capture_output=True,
                               text=True, timeout=timeout)
            out, err, code = r.stdout, r.stderr, r.returncode
        except FileNotFoundError as e:
            out, err, code = "", f"command not found: {e}", 127
        except subprocess.TimeoutExpired:
            out, err, code = "", f"timeout after {timeout}s", 124
        return {"exit_code": code, "stdout": out[-8000:], "stderr": err[-4000:],
                "sandbox_mode": self.mode, "net_off": self.mode == "full"}
