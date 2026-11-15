"""Locate the external programs owl2uml can use: Graphviz, Java and ROBOT.

Everything is optional. Each finder returns None when the tool is missing so
callers can fall back (builtin layout, rdflib loader, Python explainer).
Search order: the project-local prefix (`.local/`, filled by
scripts/setup.sh), then environment overrides, then the system PATH.
"""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX = ROOT / ".local"


def graphviz(program: str = "dot") -> tuple[str | None, dict | None]:
    """Return (path, env) for a Graphviz program such as dot, neato or unflatten."""
    local = PREFIX / "usr/bin" / program
    if local.exists():
        libdir = PREFIX / "usr/lib/x86_64-linux-gnu"
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(libdir), str(libdir / "graphviz"), env.get("LD_LIBRARY_PATH", "")]
        )
        env["GVBINDIR"] = str(libdir / "graphviz")
        return str(local), env
    found = shutil.which(program)
    return (found, None) if found else (None, None)


@lru_cache(maxsize=1)
def java() -> str | None:
    """Path to a java binary (JAVA_HOME first, then PATH)."""
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin/java").exists():
        return str(Path(home) / "bin/java")
    return shutil.which("java")


@lru_cache(maxsize=1)
def robot_jar() -> str | None:
    """Path to robot.jar: $OWL2UML_ROBOT_JAR, then .local/robot/robot.jar."""
    env = os.environ.get("OWL2UML_ROBOT_JAR")
    if env and Path(env).exists():
        return env
    local = PREFIX / "robot" / "robot.jar"
    return str(local) if local.exists() else None


def robot_cmd() -> list[str] | None:
    """Command prefix that runs ROBOT, or None when Java or the jar is missing."""
    j, jar = java(), robot_jar()
    if not (j and jar):
        return None
    heap = os.environ.get("OWL2UML_ROBOT_HEAP", "-Xmx4G")
    return [j, heap, "-jar", jar]
