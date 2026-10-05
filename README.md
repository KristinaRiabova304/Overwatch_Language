# OWL — Overwatch Workshop Language

A small statically-typed language themed after *Overwatch*: variable
declarations, types and operators are spelled with game-flavored keywords
and emoji instead of the usual `let`/`i32`/`==`. This is stage 1 of the
course project: the lexer and the recursive-descent parser that build an
AST. There is no semantic analysis or code generation yet — `+!` etc. are
parsed and recorded in the AST, but overflow is not actually checked until
stage 2.

## Language overview

### Types

| OWL       | Meaning                          |
|-----------|-----------------------------------|
| `🔫`      | `i32` equivalent (a pistol clip)  |
| `🚀`      | `i64` equivalent (a rocket, "bigger ammo") |
| `ult`     | boolean (an ultimate is either charged or not) |

### Literals

```
100          // integer literal
🔥           // true  ("ultimate charged")
💤           // false ("ultimate on cooldown")
```

### Variable declarations

`flex` declares a **mutable** variable (a flex player adapts, so the value
can change). `🔒` declares an **immutable / const** variable (locked in, the
value can never change once set).

```
flex hp: 🔫 = 100;      // mutable i32
🔒 team_size: 🔫 = 6;   // immutable i32
flex ready: ult = 🔥;   // mutable bool
```

### Assignment

```
flex hp: 🔫 = 100;
hp = 80;
```

### Comparisons

`🆚` is the `==` equivalent, `🚫` is the `!=` equivalent. Comparisons do not
chain — at most one per expression.

```
if hp 🆚 0 {
  hp = 100;
}
if hp 🚫 0 {
  hp = hp - 1;
}
```

### Arithmetic and overflow checks

Every arithmetic operator has an unchecked (wrapping) form and a checked
(overflow-checked) form, spelled with a trailing `!`:

```
flex dmg: 🔫 = 1 + 2 * 3;         // unchecked
flex dmg2: 🔫 = 1 +! 2 -! 3 *! 4 /! 5;  // overflow-checked
```

The parser records whether each operation was written as checked or
unchecked (see the `checked=` field in the `--ast` dump); actually trapping
on overflow at runtime is part of the next project stage.

### if / else

The `if` block and the `else` block each require at least one statement;
`else` is optional.

```
flex hp: 🔫 = 30;
if hp 🚫 0 {
  hp = hp - 10;
} else {
  hp = 0;
}
```

The full grammar is in [`grammar.ebnf`](grammar.ebnf).

## Building and running

Requires Python 3.9+, no dependencies.

```
python3 compiler.py --ast path/to/program.txt
```

This prints an indented dump of the AST to stdout. On a lexical or syntax
error, nothing is printed to stdout; a single line is printed to stderr:

```
compilation error: line L:C: message
```

and the process exits with a non-zero status.

## Project layout

```
lexer.py       hand-written byte-level lexer (state machine, Token/LexError)
ast_nodes.py   AST node hierarchy + the --ast dump printer
parser.py      hand-written recursive-descent parser (Parser/ParseError)
compiler.py    CLI entry point
grammar.ebnf   the complete grammar
tests/         test cases and the runner (see below)
```

## Running the tests

```
python3 tests/run_tests.py
```

This runs every program in `tests/happy/` and checks its `--ast` output
against the matching `.expected` file, then runs every program in
`tests/error/` and checks that it fails with the exact error message in its
matching `.expected` file. It prints PASS/FAIL per test and a summary, and
exits non-zero if anything failed.
