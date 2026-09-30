"""Exercise the refresh-data gate logic for real, both ways.

The point is NOT to re-read the YAML. It is to confirm that:
  - a FAILING fallback still lets the publish steps run, and then fails the job;
  - a PASSING fallback leaves the job green.

Runs the actual `if` shell and the actual GitHub `steps.<id>.outputs` mechanics
(GITHUB_OUTPUT file, `!= 'true'` comparison), so a typo in either is caught.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

WF = pathlib.Path(".github/workflows/refresh-data.yml")
doc = yaml.safe_load(WF.read_text())
steps = doc["jobs"]["refresh"]["steps"]
by_name = {s.get("name", ""): s for s in steps}

fallback = next(s for s in steps if s.get("id") == "fallback")
gate = next(s for s in steps if "Fail the run if the live fallback" in s.get("name", ""))
names = [s.get("name", "") for s in steps]

# --- structural invariants -------------------------------------------------
push_i = names.index(next(n for n in names if n.startswith("Commit & push")))
deploy_i = names.index(next(n for n in names if n.startswith("Trigger Vercel")))
gate_i = names.index(gate["name"])
fb_i = names.index(fallback["name"])

assert fb_i < push_i, "fallback must run BEFORE the commit, so a fresh latest.json is published"
assert gate_i > deploy_i, "the gate must run AFTER the deploy, or settled data stops shipping"
assert "continue-on-error" not in fallback, "fallback must not be silently swallowed"
assert gate["if"] == "steps.fallback.outputs.ok != 'true'", f"unexpected gate: {gate['if']!r}"
print(f"order ok: fallback[{fb_i}] < push[{push_i}] < deploy[{deploy_i}] < gate[{gate_i}]")

# The old silent-warning shape must be gone.
body = WF.read_text()
assert "::warning::live fallback rebuild failed" not in body, "silent warning still present"
assert "::error::live fallback rebuild FAILED" in body, "loud error missing"
print("silent-warning shape gone, loud ::error:: present")

# --- behavioural trial: run the real step body both ways -------------------
run_body = fallback["run"]


def trial(build_succeeds: bool) -> tuple[str, bool]:
    """Run the step's real shell with a stubbed `uv`, return (ok_output, gate_fires)."""
    with tempfile.TemporaryDirectory() as td:
        bind = pathlib.Path(td) / "bin"
        bind.mkdir()
        stub = bind / "uv"
        stub.write_text("#!/bin/sh\n" + ("exit 0\n" if build_succeeds else
                                         "echo 'build failed (RuntimeError)' >&2\nexit 1\n"))
        stub.chmod(0o755)
        out = pathlib.Path(td) / "gh_out"
        out.write_text("")
        env = {**os.environ,
               "PATH": f"{bind}:{os.environ['PATH']}",
               "GITHUB_OUTPUT": str(out)}
        r = subprocess.run(["bash", "-e", "-c", run_body],
                           capture_output=True, text=True, env=env)
        written = out.read_text().strip()
        ok = written.split("=", 1)[1] if "=" in written else ""
        # Reproduce GitHub's `!= 'true'` evaluation of the gate's if-expression.
        gate_fires = ok != "true"
        return (f"step_rc={r.returncode} output={written!r} "
                f"stderr={r.stderr.strip()[:40]!r}"), gate_fires


ok_line, ok_gate = trial(True)
print(f"\nbuild SUCCEEDS -> {ok_line}\n  gate fires? {ok_gate}")
assert not ok_gate, "a successful build must NOT fail the run"

bad_line, bad_gate = trial(False)
print(f"build FAILS    -> {bad_line}\n  gate fires? {bad_gate}")
assert bad_gate, "a failed build MUST fail the run"

# And the step itself must not abort the job (publish steps must still run).
assert "step_rc=0" in bad_line, "failing build aborted the step — publish path would be skipped"

print("\nPASS: fallback failure publishes settled data AND turns the run red;"
      "\n      fallback success leaves it green.")
sys.exit(0)
