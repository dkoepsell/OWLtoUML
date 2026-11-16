"""Entry point of the owl2uml GitHub Action (spec WS4.4).

On a pull request: check out the base commit next to the head, run
``owl2uml diff``, write the figures to owl2uml-diff/, post (or update) one PR
comment with the PNG and the summary, and report whether a ``fail-on``
condition held. On a push to the default branch: redraw the ontology into
``docs-dir`` and commit it when it changed.

Standard library only; inputs arrive as INPUT_* environment variables.
Without a token or repository (e.g. run locally) nothing is posted or pushed;
the comment is still written to owl2uml-diff/comment.md.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
OUT = Path("owl2uml-diff")
MARKER = "<!-- owl2uml-diff -->"
EXTS = ("owl", "ofn", "omn", "owx", "ttl", "obo")


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def git(*args, check=True, cwd=None) -> str:
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True,
                          cwd=cwd).stdout.strip()


def owl2uml(*args) -> int:
    code = (f"import sys; sys.path.insert(0, {str(SRC)!r}); "
            "from owl2uml.cli import main; sys.exit(main())")
    print("+ owl2uml " + " ".join(args), flush=True)
    return subprocess.run([sys.executable, "-c", code, *args]).returncode


def find_ontology() -> str:
    """The input, else ODK's src/ontology/<name>-edit.<ext>."""
    given = env("INPUT_ONTOLOGY")
    if given:
        return given
    for ext in EXTS:
        hits = sorted(glob.glob(f"src/ontology/*-edit.{ext}"))
        if hits:
            return hits[0]
    raise SystemExit("owl2uml: no ontology given and no src/ontology/*-edit.* found")


def output(name: str, value: str) -> None:
    path = env("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def common_args() -> list[str]:
    return ["--profile", env("INPUT_PROFILE", "none"), "--reason", env("INPUT_REASON", "hermit")]


# ---------------------------------------------------------------- pull request

def diff_mode(onto: str) -> int:
    base = env("INPUT_BASE")
    if not base:
        raise SystemExit("owl2uml: no base commit (set 'base', or run on pull_request)")
    git("fetch", "--depth=1", "origin", base, check=False)
    tmp = tempfile.mkdtemp(prefix="owl2uml-base-")
    git("worktree", "add", "--detach", tmp, base)
    try:
        old = os.path.join(tmp, onto)
        if not os.path.exists(old):
            print(f"owl2uml: {onto} does not exist at {base[:12]}; nothing to compare")
            output("failed", "false")
            return 0
        OUT.mkdir(exist_ok=True)
        args = ["diff", old, onto, "-o", str(OUT / "diff.svg"), "--export", "png,svg-static",
                "--diff-scope", env("INPUT_DIFF_SCOPE", "1hop"), "--interactive"] + common_args()
        if env("INPUT_FAIL_ON"):
            args += ["--fail-on", env("INPUT_FAIL_ON")]
        rc = owl2uml(*args)
    finally:
        git("worktree", "remove", "--force", tmp, check=False)
    if rc not in (0, 3):
        raise SystemExit(rc)
    data = json.loads((OUT / "diff.json").read_text(encoding="utf-8"))
    image = push_image(OUT / "diff.png") if (OUT / "diff.png").exists() else ""
    sys.path.insert(0, str(SRC))
    from owl2uml.diff.report import markdown
    failed = data.get("fail_on", {}).get("failed", [])
    body = markdown(data, title=f"Ontology changes in `{onto}`", image=image, failed=failed)
    run_url = run_link()
    if run_url:
        body += f"\nFigures (interactive SVG, static SVG, PNG, diff.json): [workflow run]({run_url})\n"
    (OUT / "comment.md").write_text(MARKER + "\n" + body, encoding="utf-8")
    summary = env("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(body)
    if env("INPUT_COMMENT", "true") == "true":
        post_comment(MARKER + "\n" + body)
    output("failed", "true" if failed else "false")
    output("summary", str(OUT / "diff.md"))
    return 0


def run_link() -> str:
    repo, rid = env("GITHUB_REPOSITORY"), env("GITHUB_RUN_ID")
    return f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{rid}" \
        if repo and rid else ""


def push_image(png: Path) -> str:
    """Commit the PNG to the image branch (keeping what is there) and return
    a URL a comment can show. Empty when there is no branch or push fails."""
    branch, repo, pr = env("INPUT_IMAGE_BRANCH"), env("GITHUB_REPOSITORY"), env("PR_NUMBER")
    if not (branch and repo and env("GITHUB_TOKEN")):
        return ""
    name = f"pr{pr or 'x'}-{env('GITHUB_SHA', 'head')[:10]}.png"
    try:
        blob = git("hash-object", "-w", str(png))
        git("fetch", "--depth=1", "origin", f"{branch}:refs/remotes/origin/{branch}", check=False)
        parent = git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}", check=False)
        entries = git("ls-tree", parent).splitlines() if parent else []
        entries = [e for e in entries if not e.endswith("\t" + name)]
        entries.append(f"100644 blob {blob}\t{name}")
        tree = subprocess.run(["git", "mktree"], input="\n".join(entries) + "\n", text=True,
                              capture_output=True, check=True).stdout.strip()
        ident = ["-c", "user.name=github-actions[bot]",
                 "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
        commit = git(*ident, "commit-tree", tree, *(["-p", parent] if parent else []),
                     "-m", f"owl2uml diagram for PR {pr}")
        git("push", "origin", f"{commit}:refs/heads/{branch}")
    except subprocess.CalledProcessError as exc:
        print(f"owl2uml: could not push the image ({exc.stderr or exc}); comment without it")
        return ""
    return f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/raw/{branch}/{name}"


def api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{env('GITHUB_API_URL', 'https://api.github.com')}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {env('GITHUB_TOKEN')}",
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def post_comment(body: str) -> None:
    repo, pr = env("GITHUB_REPOSITORY"), env("PR_NUMBER")
    if not (repo and pr and env("GITHUB_TOKEN")):
        print("owl2uml: not on a pull request with a token; comment written to "
              f"{OUT / 'comment.md'} only")
        return
    try:
        mine = [c for c in api("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100")
                if MARKER in (c.get("body") or "")]
        if mine:
            api("PATCH", f"/repos/{repo}/issues/comments/{mine[-1]['id']}", {"body": body})
        else:
            api("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})
    except OSError as exc:      # urllib errors: a missing permission must not hide the diff
        print(f"owl2uml: could not comment on the pull request: {exc}")


# ---------------------------------------------------------------- default branch

def docs_mode(onto: str) -> int:
    docs = env("INPUT_DOCS_DIR")
    if not docs:
        print("owl2uml: docs-dir is empty; nothing to update")
        return 0
    Path(docs).mkdir(parents=True, exist_ok=True)
    stem = Path(onto).name.rsplit(".", 1)[0]
    out = str(Path(docs) / f"{stem}.svg")
    args = [onto, "-o", out, "--export", "svg-static,png", "--interactive",
            "--coverage-out", "-"] + common_args()
    rc = owl2uml(*args)
    if rc == 0 and env("INPUT_MODULES") == "true":
        rc = owl2uml(onto, "-o", out, "--all-modules", "--coverage-out", "-", *common_args())
    if rc != 0:
        return rc
    git("add", docs)
    if not git("status", "--porcelain", docs):
        print("owl2uml: diagrams unchanged")
        return 0
    if not env("GITHUB_TOKEN"):
        print(f"owl2uml: diagrams updated in {docs} (no token: not committed)")
        return 0
    ident = ["-c", "user.name=github-actions[bot]",
             "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
    git(*ident, "commit", "-m", f"Update ontology diagrams ({docs}) [skip ci]")
    git("push", "origin", "HEAD")
    print(f"owl2uml: committed the updated diagrams in {docs}")
    return 0


def main() -> int:
    onto = find_ontology()
    event = env("GITHUB_EVENT_NAME")
    ref, default = env("GITHUB_REF"), env("DEFAULT_BRANCH", "main")
    if event == "push" and ref == f"refs/heads/{default}":
        return docs_mode(onto)
    if event in ("pull_request", "pull_request_target") or env("INPUT_BASE"):
        return diff_mode(onto)
    print(f"owl2uml: nothing to do on '{event or 'local'}' (no base commit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
