"""WS4.4: the GitHub Action's entry script, run locally on a throwaway ODK-style
repository (no token: nothing is posted or pushed)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from owl2uml.dot import dot_available  # noqa: E402

pytestmark = pytest.mark.skipif(not dot_available(), reason="needs graphviz")


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    from test_diff import seeded
    old, new = seeded()
    onto = tmp_path / "src" / "ontology"
    onto.mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main")
    old.serialize(onto / "lof-edit.ttl", format="turtle")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "old")
    base = _git(tmp_path, "rev-parse", "HEAD")
    new.serialize(onto / "lof-edit.ttl", format="turtle")
    _git(tmp_path, "commit", "-q", "-am", "new")
    return tmp_path, base


def _run(repo, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "INPUT_"))}
    env.update({"INPUT_REASON": "none", "INPUT_PROFILE": "none",
                "GITHUB_OUTPUT": str(repo / "out.txt"),
                "GITHUB_STEP_SUMMARY": str(repo / "summary.md")}, **extra)
    return subprocess.run([sys.executable, str(ROOT / "action" / "run.py")], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=600)


def test_pull_request_diff(repo):
    path, base = repo
    p = _run(path, GITHUB_EVENT_NAME="pull_request", INPUT_BASE=base,
             INPUT_FAIL_ON="removed-without-deprecation")
    assert p.returncode == 0, p.stderr
    out = path / "owl2uml-diff"
    for f in ("diff.svg", "diff.png", "diff-static.svg", "diff.json", "diff.md", "comment.md"):
        assert (out / f).exists(), f
    assert "failed=true" in (path / "out.txt").read_text()
    comment = (out / "comment.md").read_text()
    assert comment.startswith("<!-- owl2uml-diff -->") and "lof-edit.ttl" in comment
    assert "| entities |" in (path / "summary.md").read_text()
    # the base worktree is cleaned up
    assert len(_git(path, "worktree", "list").splitlines()) == 1


def test_push_to_default_branch_updates_docs(repo):
    path, _ = repo
    p = _run(path, GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main",
             DEFAULT_BRANCH="main", INPUT_DOCS_DIR="docs/diagrams")
    assert p.returncode == 0, p.stderr
    assert (path / "docs" / "diagrams" / "lof-edit.svg").exists()
    assert (path / "docs" / "diagrams" / "lof-edit.png").exists()
