#!/usr/bin/env python3
"""Runs every OWL test case and reports which ones fail.

Happy-path cases (tests/happy/*.txt) must compile and produce the AST dump
stored in the matching *.expected file.

Error cases (tests/error/*.txt) must fail to compile with a non-zero exit
code and the stderr message stored in the matching *.expected file.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "compiler.py"
HAPPY_DIR = Path(__file__).resolve().parent / "happy"
ERROR_DIR = Path(__file__).resolve().parent / "error"


def run_compiler(src_path, with_ast):
    cmd = [sys.executable, str(COMPILER)]
    if with_ast:
        cmd.append("--ast")
    cmd.append(str(src_path))
    return subprocess.run(cmd, capture_output=True, text=True)


def check_happy(src_path):
    expected_path = src_path.with_suffix(".expected")
    expected = expected_path.read_text()
    proc = run_compiler(src_path, with_ast=True)
    if proc.returncode != 0:
        return False, f"expected success, got exit code {proc.returncode}: {proc.stderr.strip()}"
    if proc.stdout != expected:
        return False, f"AST dump mismatch\n--- expected ---\n{expected}--- actual ---\n{proc.stdout}"
    return True, ""


def check_error(src_path):
    expected_path = src_path.with_suffix(".expected")
    expected = expected_path.read_text()
    proc = run_compiler(src_path, with_ast=False)
    if proc.returncode == 0:
        return False, "expected a compilation error, but compilation succeeded"
    if proc.stdout != "":
        return False, f"expected no stdout on error, got: {proc.stdout!r}"
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
            failures.append((src.name, message))
    return len(sources), failures


def main():
    happy_total, happy_failures = run_suite(HAPPY_DIR, check_happy, "happy")
    error_total, error_failures = run_suite(ERROR_DIR, check_error, "error")

    total = happy_total + error_total
    failures = happy_failures + error_failures

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
