#!/usr/bin/env python3
"""Entry point for the OWL compiler (stage 1: lexer + parser -> AST dump)."""

import argparse
import sys

from lexer import Lexer, LexError
from parser import Parser, ParseError
from ast_nodes import dump_ast


def main():
    argp = argparse.ArgumentParser(description="OWL (Overwatch Workshop Language) compiler")
    argp.add_argument("input", help="path to an OWL source file")
    argp.add_argument("--ast", action="store_true", help="print the parsed AST")
    args = argp.parse_args()

    with open(args.input, "rb") as f:
        source = f.read()

    try:
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse_program()
    except (LexError, ParseError) as e:
        print(f"compilation error: line {e.line}:{e.col}: {e.message}", file=sys.stderr)
        sys.exit(1)

    if args.ast:
        for line in dump_ast(program):
            print(line)


if __name__ == "__main__":
    main()
