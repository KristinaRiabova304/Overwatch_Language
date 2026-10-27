#!/usr/bin/env python3
"""Runs every OWL test case and reports which ones fail.

tests/happy/NAME.txt   must parse; `--ast` output must equal NAME.expected.
tests/run/NAME.txt     end to end: compiled to .ll, built with clang and run.
                       Its stdout must equal NAME.expected exactly. When
                       NAME.in exists it is the program's standard input;
                       when NAME.exitcode exists the exit code must match it
                       (otherwise it must be 0).
tests/error/NAME.txt   must fail to compile with no stdout, a non-zero exit
                       code, no output file and the stderr in NAME.expected.

The C compiler is taken from $CLANG, else `clang` on PATH.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "compiler.py"
TESTS = Path(__file__).resolve().parent
HAPPY_DIR = TESTS / "happy"
RUN_DIR = TESTS / "run"
ERROR_DIR = TESTS / "error"

CLANG = os.environ.get("CLANG") or shutil.which("clang")


def compile_to_ll(src_path, out_path):
    cmd = [sys.executable, str(COMPILER), str(src_path), str(out_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


def check_happy(src_path):
    expected = src_path.with_suffix(".expected").read_text()
    cmd = [sys.executable, str(COMPILER), "--ast", str(src_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False, f"expected success, got exit code {proc.returncode}: {proc.stderr.strip()}"
    if proc.stdout != expected:
        return False, f"AST dump mismatch\n--- expected ---\n{expected}--- actual ---\n{proc.stdout}"
    return True, ""


def check_run(src_path):
    expected = src_path.with_suffix(".expected").read_text()
    input_path = src_path.with_suffix(".in")
    exitcode_path = src_path.with_suffix(".exitcode")
    expected_code = int(exitcode_path.read_text()) if exitcode_path.exists() else 0
    stdin = input_path.read_text() if input_path.exists() else ""

    with tempfile.TemporaryDirectory() as tmp:
        ll_path = Path(tmp) / "out.ll"
        exe_path = Path(tmp) / "out"
        proc = compile_to_ll(src_path, ll_path)
        if proc.returncode != 0:
            return False, f"compilation failed: {proc.stderr.strip()}"
        build = subprocess.run([CLANG, "-Wno-override-module", str(ll_path), "-o", str(exe_path)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            return False, f"clang failed:\n{build.stderr}"
        try:
            run = subprocess.run([str(exe_path)], input=stdin, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return False, "program timed out"

    if run.stdout != expected:
        return False, f"output mismatch\n--- expected ---\n{expected}--- actual ---\n{run.stdout}"
    if run.returncode != expected_code:
        return False, f"expected exit code {expected_code}, got {run.returncode} (stderr: {run.stderr.strip()!r})"
    return True, ""


def check_error(src_path):
    expected = src_path.with_suffix(".expected").read_text()
    with tempfile.TemporaryDirectory() as tmp:
        ll_path = Path(tmp) / "out.ll"
        proc = compile_to_ll(src_path, ll_path)
        wrote_output = ll_path.exists()
    if proc.returncode == 0:
        return False, "expected a compilation error, but compilation succeeded"
    if proc.stdout != "":
        return False, f"expected no stdout on error, got: {proc.stdout!r}"
    if wrote_output:
        return False, "an output file was written despite the error"
    if proc.stderr != expected:
        return False, f"stderr mismatch\n  expected: {expected.strip()!r}\n  actual:   {proc.stderr.strip()!r}"
    return True, ""


def run_suite(directory, checker, label):
    sources = sorted(directory.glob("*.txt"))
    failures = []
    for src in sources:
        ok, message = checker(src)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}/{src.name}")
        if not ok:
            failures.append((f"{label}/{src.name}", message))
    return len(sources), failures


def main():
    if CLANG is None:
        print("clang not found: install it or set $CLANG", file=sys.stderr)
        sys.exit(2)

    total, failures = 0, []
    for directory, checker, label in ((HAPPY_DIR, check_happy, "happy"),
                                      (RUN_DIR, check_run, "run"),
                                      (ERROR_DIR, check_error, "error")):
        count, failed = run_suite(directory, checker, label)
        total += count
        failures += failed

    print()
    print(f"{total - len(failures)}/{total} tests passed")
    if failures:
        print()
        print("Failed tests:")
        for name, message in failures:
            print(f"  - {name}: {message}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
