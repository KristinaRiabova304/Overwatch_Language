#!/usr/bin/env python3
"""Entry point for the OWL compiler.

  python3 compiler.py input.txt output.ll   compile to LLVM IR
  python3 compiler.py --ast input.txt       print the AST
"""

import argparse
import sys

from lexer import Lexer, LexError
from parser import Parser, ParseError
from semantic import analyze, SemanticError
from ast_nodes import dump_ast


def fail(message):
    print(f"compilation error: {message}", file=sys.stderr)
    sys.exit(1)


def main():
    argp = argparse.ArgumentParser(description="OWL (Overwatch Workshop Language) compiler")
    argp.add_argument("input", help="path to an OWL source file")
    argp.add_argument("output", nargs="?", help="path of the LLVM IR file to write")
    argp.add_argument("--ast", action="store_true", help="print the parsed AST")
    args = argp.parse_args()

    try:
        with open(args.input, "rb") as f:
            source = f.read()
    except OSError as e:
        fail(f"cannot read {args.input}: {e.strerror}")

    try:
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse_program()
        if args.ast:
            for line in dump_ast(program):
                print(line)
            return
        analyze(program)
    except (LexError, ParseError, SemanticError) as e:
        fail(f"line {e.line}:{e.col}: {e.message}")
    except RecursionError:
        fail("line 1:1: program is nested too deeply")


if __name__ == "__main__":
    main()
