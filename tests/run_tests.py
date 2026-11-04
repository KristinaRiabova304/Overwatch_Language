#!/usr/bin/env python3
"""Runs every OWL test case and reports which ones fail.

tests/happy/NAME.txt     must parse; `--ast` output must equal NAME.expected.
                         With --optimize the program must behave the same
                         way, or be rejected the same way when it only parses.
tests/run/NAME.txt       end to end: compiled to .ll, built with clang and run.
                         Its stdout must equal NAME.expected exactly. When
                         NAME.in exists it is the program's standard input;
                         when NAME.exitcode exists the exit code must match it
                         (otherwise it must be 0).
tests/error/NAME.txt     must fail to compile with no stdout, a non-zero exit
                         code, no output file and the stderr in NAME.expected.
tests/optimize/NAME.txt  `--optimize --ast` output must equal NAME.ast, and the
                         program must print NAME.expected with and without the
                         flag (NAME.in and NAME.exitcode as in tests/run).
programs/NAME.txt        each recorded session, NAME.in or NAME.*.in, must print
                         its .expected exactly, with and without the flag.

Every run and error test is checked twice: without and with --optimize.

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
OPTIMIZE_DIR = TESTS / "optimize"
PROGRAMS_DIR = ROOT / "programs"

CLANG = os.environ.get("CLANG") or shutil.which("clang")
OPTIMIZE = ["--optimize"]


def compile_to_ll(src_path, out_path, flags=()):
    cmd = [sys.executable, str(COMPILER), *flags, str(src_path), str(out_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


def print_ast(src_path, flags=()):
    cmd = [sys.executable, str(COMPILER), *flags, "--ast", str(src_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


def build_and_run(src_path, stdin, flags=()):
    """Returns (error message or None, completed process of the program)."""
    with tempfile.TemporaryDirectory() as tmp:
        ll_path = Path(tmp) / "out.ll"
        exe_path = Path(tmp) / "out"
        proc = compile_to_ll(src_path, ll_path, flags)
        if proc.returncode != 0:
            return f"compilation failed: {proc.stderr.strip()}", None
        build = subprocess.run([CLANG, "-Wno-override-module", str(ll_path), "-o", str(exe_path)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            return f"clang failed:\n{build.stderr}", None
        try:
            run = subprocess.run([str(exe_path)], input=stdin, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return "program timed out", None
    return None, run


def check_output(src_path, stdin, expected, expected_code, flags=()):
    error, run = build_and_run(src_path, stdin, flags)
    if error:
        return False, error
    if run.stdout != expected:
        return False, f"output mismatch\n--- expected ---\n{expected}--- actual ---\n{run.stdout}"
    if run.returncode != expected_code:
        return False, f"expected exit code {expected_code}, got {run.returncode} (stderr: {run.stderr.strip()!r})"
    return True, ""


def read_case(src_path):
    """The expected output, stdin and exit code of a test program."""
    input_path = src_path.with_suffix(".in")
    exitcode_path = src_path.with_suffix(".exitcode")
    expected = src_path.with_suffix(".expected").read_text()
    stdin = input_path.read_text() if input_path.exists() else ""
    expected_code = int(exitcode_path.read_text()) if exitcode_path.exists() else 0
    return expected, stdin, expected_code


def check_happy(src_path):
    expected = src_path.with_suffix(".expected").read_text()
    proc = print_ast(src_path)
    if proc.returncode != 0:
        return False, f"expected success, got exit code {proc.returncode}: {proc.stderr.strip()}"
    if proc.stdout != expected:
        return False, f"AST dump mismatch\n--- expected ---\n{expected}--- actual ---\n{proc.stdout}"
    return check_same_behaviour(src_path)


def check_same_behaviour(src_path):
    plain_error, plain = build_and_run(src_path, "")
    optimized_error, optimized = build_and_run(src_path, "", OPTIMIZE)
    if plain_error == optimized_error is not None:
        return True, ""  # some of these programs only parse: both modes reject them alike
    if plain_error or optimized_error:
        return False, f"with --optimize: {plain_error or optimized_error}"
    if (plain.stdout, plain.returncode) != (optimized.stdout, optimized.returncode):
        return False, f"--optimize changed the behaviour: {plain.stdout!r} vs {optimized.stdout!r}"
    return True, ""


def check_run(src_path):
    expected, stdin, expected_code = read_case(src_path)
    return check_output(src_path, stdin, expected, expected_code)


def check_run_optimized(src_path):
    expected, stdin, expected_code = read_case(src_path)
    return check_output(src_path, stdin, expected, expected_code, OPTIMIZE)


def check_error(src_path, flags=()):
    expected = src_path.with_suffix(".expected").read_text()
    with tempfile.TemporaryDirectory() as tmp:
        ll_path = Path(tmp) / "out.ll"
        proc = compile_to_ll(src_path, ll_path, flags)
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


def check_error_optimized(src_path):
    return check_error(src_path, OPTIMIZE)


def check_optimize(src_path):
    expected_tree = src_path.with_suffix(".ast").read_text()
    proc = print_ast(src_path, OPTIMIZE)
    if proc.returncode != 0:
        return False, f"expected success, got exit code {proc.returncode}: {proc.stderr.strip()}"
    if proc.stdout != expected_tree:
        return False, f"optimized tree mismatch\n--- expected ---\n{expected_tree}--- actual ---\n{proc.stdout}"
    expected, stdin, expected_code = read_case(src_path)
    ok, message = check_output(src_path, stdin, expected, expected_code)
    if not ok:
        return False, f"without --optimize: {message}"
    ok, message = check_output(src_path, stdin, expected, expected_code, OPTIMIZE)
    if not ok:
        return False, f"with --optimize: {message}"
    return True, ""


def check_program_session(src_path, input_path):
    stdin = input_path.read_text()
    expected = input_path.with_suffix(".expected").read_text()
    for flags in ((), OPTIMIZE):
        ok, message = check_output(src_path, stdin, expected, 0, flags)
        if not ok:
            return False, f"{' '.join(flags) or 'no flag'}: {message}"
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


def run_programs():
    total, failures = 0, []
    for src in sorted(PROGRAMS_DIR.glob("*.txt")):
        for input_path in [src.with_suffix(".in")] + sorted(PROGRAMS_DIR.glob(f"{src.stem}.*.in")):
            total += 1
            ok, message = check_program_session(src, input_path)
            print(f"[{'PASS' if ok else 'FAIL'}] programs/{input_path.name}")
            if not ok:
                failures.append((f"programs/{input_path.name}", message))
    return total, failures


def main():
    if CLANG is None:
        print("clang not found: install it or set $CLANG", file=sys.stderr)
        sys.exit(2)

    total, failures = 0, []
    for directory, checker, label in ((HAPPY_DIR, check_happy, "happy"),
                                      (RUN_DIR, check_run, "run"),
                                      (RUN_DIR, check_run_optimized, "run --optimize"),
                                      (ERROR_DIR, check_error, "error"),
                                      (ERROR_DIR, check_error_optimized, "error --optimize"),
                                      (OPTIMIZE_DIR, check_optimize, "optimize")):
        count, failed = run_suite(directory, checker, label)
        total += count
        failures += failed
    count, failed = run_programs()
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
