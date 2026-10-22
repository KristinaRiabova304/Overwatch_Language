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
from codegen import generate
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
    if not args.ast and args.output is None:
        argp.error("an output file is required unless --ast is given")

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
        module = generate(program)
    except (LexError, ParseError, SemanticError) as e:
        fail(f"line {e.line}:{e.col}: {e.message}")
    except RecursionError:
        fail("line 1:1: program is nested too deeply")
    except Exception as e:  # a bug in the compiler itself: still one line, never a traceback
        fail(f"line 1:1: internal compiler error: {type(e).__name__}: {e}")

    # The output file is written only after everything succeeded.
    try:
        with open(args.output, "w") as f:
            f.write(str(module))
    except OSError as e:
        fail(f"cannot write {args.output}: {e.strerror}")


if __name__ == "__main__":
    main()
