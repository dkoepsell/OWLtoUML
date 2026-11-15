"""Locate the external programs owl2uml can use: Graphviz, Java and ROBOT.

Everything is optional. Each finder returns None when the tool is missing so
callers can fall back (builtin layout, rdflib loader, Python explainer).
Search order: the project-local prefix (`.local/`, filled by
scripts/setup.sh), then environment overrides, then the system PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
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


_HELPER_SRC = Path(__file__).resolve().parent / "java" / "O2uConvert.java"
HELPER_DIR = PREFIX / "o2u"


def compile_helper() -> bool:
    """Compile O2uConvert.java against robot.jar into .local/o2u (no javac
    binary needed: the JDK's compiler module is run through `java -m`)."""
    j, jar = java(), robot_jar()
    if not (j and jar):
        return False
    try:
        HELPER_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([j, "-m", "jdk.compiler/com.sun.tools.javac.Main", "-nowarn",
                            "-cp", jar, "-d", str(HELPER_DIR), str(_HELPER_SRC)],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def convert_cmd() -> list[str] | None:
    """Command prefix for the O2uConvert helper, or None without Java + ROBOT.

    Uses the compiled class when it is up to date, compiles it on first use,
    and otherwise runs the source file directly (slower: compiles each run).
    """
    j, jar = java(), robot_jar()
    if not (j and jar):
        return None
    heap = os.environ.get("OWL2UML_ROBOT_HEAP", "-Xmx4G")
    cls = HELPER_DIR / "O2uConvert.class"
    fresh = cls.exists() and cls.stat().st_mtime >= _HELPER_SRC.stat().st_mtime
    if fresh or compile_helper():
        return [j, heap, "-cp", os.pathsep.join([jar, str(HELPER_DIR)]), "O2uConvert"]
    return [j, heap, "-cp", jar, str(_HELPER_SRC)]


def robot_cmd() -> list[str] | None:
    """Command prefix that runs ROBOT, or None when Java or the jar is missing."""
    j, jar = java(), robot_jar()
    if not (j and jar):
        return None
    heap = os.environ.get("OWL2UML_ROBOT_HEAP", "-Xmx4G")
    return [j, heap, "-jar", jar]
