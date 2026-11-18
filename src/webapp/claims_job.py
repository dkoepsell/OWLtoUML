"""Background runner for one web claims job: ``python claims_job.py JOBDIR``.

Started detached by claims_api.py. Waits its turn (one reasoner run per
server), runs ``owl2uml claims`` with a time limit, and falls back to the
assertions alone when the ontology is over the check budget or the reasoners
run out of time. Progress goes to JOBDIR/state.json; results to JOBDIR/out/.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = ("import sys; sys.path.insert(0, sys.argv[1]); "
       "from owl2uml.claims.cli import main; sys.exit(main(sys.argv[2:]))")


def _state(job: str, **kw) -> None:
    path = os.path.join(job, "state.json")
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    st.update(kw)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    os.replace(path + ".tmp", path)


def _claims(job: str, meta: dict, extra: list[str], timeout: float):
    cmd = [sys.executable, "-c", RUN, SRC, os.path.join(job, "ontology.ttl"),
           "--out-dir", os.path.join(job, "out"), "--format", "jsonl,txt",
           "--imports", "none", "--offline", "--max-probes", str(meta["max_checks"])]
    if meta.get("native_ns"):
        cmd += ["--native-ns", meta["native_ns"]]
    with open(os.path.join(job, "stderr.log"), "a", encoding="utf-8") as err:
        try:
            return subprocess.run(cmd + extra, stdout=subprocess.DEVNULL, stderr=err,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return None


def main(job: str) -> None:
    with open(os.path.join(job, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    note = meta.get("note")
    rc = 0
    if meta["mode"] == "full":
        _state(job, state="queued")
        with open(meta["lock"], "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)          # one reasoner run at a time
            _state(job, state="running", started=time.time())
            rc = _claims(job, meta, [], meta["timeout"])
        if rc is None:
            note = (f"The reasoners did not finish within {meta['timeout'] // 60:.0f} minutes, so "
                    "only the assertions are listed. Run `owl2uml claims` locally for the "
                    "inferences.")
        elif rc == 6:
            note = "The ontology is over the reasoner check budget, so only the assertions are listed."
        if rc in (None, 6):
            meta["mode"] = "assertions"
    if meta["mode"] == "assertions":
        _state(job, state="running", started=time.time(), mode="assertions")
        rc = _claims(job, meta, ["--assertions-only"], 120)
        rc = -1 if rc is None else rc
    _state(job, state="done", rc=rc, note=note, finished=time.time())


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as exc:  # noqa: BLE001 - the page must hear about it
        _state(sys.argv[1], state="done", rc=-1, note=None, crash=str(exc))
