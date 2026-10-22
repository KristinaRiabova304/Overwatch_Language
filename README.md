# OWL — Overwatch Workshop Language

A small statically-typed language themed after *Overwatch*: declarations,
types and operators are spelled with game-flavored keywords and emoji
instead of the usual `let`/`i32`/`==`. Stage 2 makes the language run: the
compiler checks a program in a separate semantic pass and generates LLVM IR
through the `llvmlite.ir` builder, which clang turns into an executable.

The full grammar is in [`grammar.ebnf`](grammar.ebnf).

## Building and running

Requirements: Python 3.9+, [llvmlite](https://pypi.org/project/llvmlite/)
and clang (any version that reads the IR llvmlite prints; tested with
llvmlite 0.49 and clang 23).

```
python3 -m pip install -r requirements.txt
```

If pip refuses with "externally-managed-environment" (Homebrew or Linux
distribution Pythons), install into a virtual environment instead:

```
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Compile a program to LLVM IR, build it and run it:

```
python3 compiler.py program.txt program.ll
clang program.ll -o program
./program
```

clang may warn that it overrides the module's target triple; the warning
is harmless (`-Wno-override-module` silences it). `lli program.ll` also runs
the IR directly.

Print the AST instead (parsing only, no semantic checks):

```
python3 compiler.py --ast program.txt
```

On any error — lexical, syntax or semantic — nothing is written to stdout,
no output file is created, the exit code is 1, and one line goes to stderr:

```
compilation error: line L:C: message
```

`L:C` is the line and column of the token that broke the rule. Columns
count bytes, as in stage 1, so an emoji such as `🔫` is 4 columns wide.

## Running the tests

```
python3 tests/run_tests.py
```

| Directory      | What is checked |
|----------------|-----------------|
| `tests/happy/` | `--ast` output equals `NAME.expected` |
| `tests/run/`   | end to end: compiled to `.ll`, built with clang and run; stdout equals `NAME.expected` exactly. `NAME.in`, when present, is the program's stdin; `NAME.exitcode`, when present, is the expected exit code (otherwise 0) |
| `tests/error/` | compilation fails with exactly the line in `NAME.expected`, no stdout and no output file |

The script prints PASS/FAIL per test and the list of failures, and exits
non-zero if anything failed. It uses `$CLANG` if set, else `clang` on PATH.

## The language

### Types

| OWL    | Meaning |
|--------|---------|
| `🔫`   | 32-bit signed integer (a pistol clip) |
| `🚀`   | 64-bit signed integer (a rocket, "bigger ammo") |
| `ult`  | boolean (an ultimate is either charged or not) |
| `Name` | a structure declared with `hero` |

Literals: `100`, `🔥` (true, "ultimate charged"), `💤` (false, "on cooldown"),
and string literals `"..."`, which can only be printed.

### Variables

`flex` declares a mutable variable (a flex player adapts); `🔒` declares a
constant one (locked in).

```
flex hp: 🔫 = 100;
🔒 team_size: 🔫 = 6;
hp = 80;
```

### Operators

`+ - * /` wrap around on overflow; the checked forms `+! -! *! /!` stop the
program instead. `🆚` is `==`, `🚫` is `!=`; comparisons do not chain.

```
flex dmg: 🔫 = 1 +! 2 *! 3;
flex same: ult = dmg 🆚 7;
```

### if / else

```
if hp 🚫 0 {
  hp = hp - 10;
} else {
  hp = 0;
}
```

### Functions

`ability` declares a function with typed parameters and a result type;
`gg` ("good game") leaves it with a value. A call is an expression.

```
ability heal(hp: 🔫, amount: 🔫) -> 🔫 {
  gg hp +! amount;
}
flex hp: 🔫 = heal(50, heal(10, 5));
```

### Structures

`hero` declares a structure. Fields use the same `flex` / `🔒` keywords as
variables; `spawn` creates an object with one value per field, in order.

```
hero Point {
  flex x: 🔫;
  🔒 y: 🔫;
}
hero Circle {
  flex center: Point;
  🔒 r: 🔫;
}
flex c: Circle = spawn Circle(spawn Point(1, 2), 5);
c.center.x = 10;
```

### Member functions

An `ability` inside a `hero` is a member function. Its body sees the
object's fields and the other member functions by name; it is called on
an object with `.`.

```
hero Point {
  flex x: 🔫;
  🔒 y: 🔫;
  ability d2() -> 🔫 { gg x * x + y * y; }
  ability move(dx: 🔫) -> 🔫 { x = x + dx; gg x; }
}
flex p: Point = spawn Point(3, 4);
p.move(1);
print(p.d2());
```

### read and print

`read()` reads one integer from standard input. `print(...)` prints an
integer, a bool, a string literal or an object, followed by a newline.

```
flex n: 🔫 = read();
print("you typed:");
print(n);
print(spawn Point(n, 0));
```

### Leaving the program

`gg` at the top level ends the program; its value is the exit code.

```
gg 0;
```

## Semantic rules

The semantic pass (`semantic.py`) enforces these rules before any code is
generated. Each rule is covered by a test that follows it and one that
breaks it; the test names are given after each rule (`run/` and `happy/`
programs follow the rule, `error/` programs break it).

### Types

1. **Operands have the same type.** `+ - * /` and their checked forms take
   two integers of the same type (two `🔫` or two `🚀`) and give that type.
   `🆚` and `🚫` take two `🔫`, two `🚀` or two `ult` and give `ult`.
   Objects cannot be compared. There are no implicit conversions.
   *Follows:* `run/arithmetic_widths`. *Breaks:* `error/mixed_int_types`,
   `error/arithmetic_on_bool`, `error/compare_objects`.
2. **An integer literal takes the type it is used as, and must fit in it.**
   In `flex x: 🚀 = 5;` the 5 is a `🚀`; next to another operand it takes
   that operand's type; otherwise it is a `🔫`. `-2147483648` is a valid
   `🔫`; `3000000000` is not.
   *Follows:* `run/arithmetic_widths`. *Breaks:* `error/literal_too_big`.
3. **A condition is `ult`.**
   *Follows:* `run/if_else_nested`. *Breaks:* `error/condition_not_bool`.
4. **A value must have the type of the place it goes to**: the declared
   type of a variable, the type of an assigned variable or field, the type
   of a parameter, the result type of a function, the type of a field in
   `spawn`.
   *Follows:* `run/struct_chains`. *Breaks:* `error/wrong_argument_type`,
   `error/spawn_wrong_type`, `error/read_into_i64`.

### Overflow (checked at run time)

5. **Unchecked arithmetic wraps; checked arithmetic stops the program.**
   `+ - *` and `/` wrap around in two's complement (so `-2147483648 / -1`
   is `-2147483648`). When `+! -! *! /!` overflow, the program prints
   `runtime error: integer overflow` to stderr and exits with code 1.
   Division by zero, with `/` or `/!`, prints
   `runtime error: division by zero` and exits with code 1. Output printed
   before the error is kept.
   *Follows:* `run/arithmetic_widths`. *Breaks (at run time):*
   `run/checked_overflow_trap`, `run/division_by_zero_trap`.

### Scopes and variables

6. **A name is declared before it is used, and once per scope.** The top
   level, every function body (together with its parameters) and every
   `{ }` block of an `if` is a scope. An inner block may declare a name
   that an outer scope already has; it hides the outer one until the
   block ends.
   *Follows:* `run/name_lookup`. *Breaks:* `error/undeclared_variable`,
   `error/duplicate_declaration`.
7. **Only `flex` variables can be assigned.**
   *Follows:* `run/if_else_nested`. *Breaks:* `error/assign_to_constant`.

### Functions

8. **What a function body can see:** its parameters, its own locals, the
   top-level variables declared *above* the function, and every function
   in the program (a function may call itself and functions declared
   below it). Top-level variables are globals.
   *Follows:* `run/name_lookup`, `run/forward_calls`.
   *Breaks:* `error/global_declared_below`, `error/unknown_function`.
9. **A call passes exactly as many arguments as the function has
   parameters, each of the parameter's type.** The result of the call has
   the function's result type.
   *Follows:* `run/functions_recursion`. *Breaks:*
   `error/too_many_arguments`, `error/too_few_arguments`,
   `error/wrong_argument_type`.
10. **Parameters are constant.** A parameter cannot be assigned, and a
    mutating member function cannot be called on it.
    *Follows:* `run/objects_by_value`. *Breaks:*
    `error/assign_to_parameter`, `error/mutating_call_on_parameter`.
11. **Every path through a function ends in `gg`, with a value of the
    result type.** An `if` ends every path only when both branches do. A
    statement after `gg` in the same block is an error.
    *Follows:* `run/functions_recursion`. *Breaks:*
    `error/wrong_return_type`, `error/missing_gg`,
    `error/unreachable_after_gg`.
12. **Function names are unique**, and differ from structure names.
    *Follows:* `run/runtime_name_clash`. *Breaks:*
    `error/duplicate_function`.
13. **`gg` at the top level takes a `🔫`, which becomes the exit code.** A
    program without a top-level `gg` exits with 0.
    *Follows:* `run/exit_code`. *Breaks:* `error/exit_code_not_i32`.

### Structures

14. **A field's type is `🔫`, `🚀`, `ult`, or a structure declared above.**
    A structure cannot contain itself, and field and member function names
    are unique within a structure.
    *Follows:* `run/struct_chains`. *Breaks:*
    `error/struct_contains_itself`, `error/struct_declared_below`,
    `error/duplicate_field`.
15. **`spawn` gives one value per field, in declaration order.**
    *Follows:* `run/struct_chains`. *Breaks:* `error/spawn_wrong_count`,
    `error/spawn_wrong_type`.
16. **A field or member function is accessed only if the structure has
    it.**
    *Follows:* `run/struct_chains`. *Breaks:* `error/unknown_field`,
    `error/unknown_member_function`.
17. **Objects are values.** Initialising or assigning an object, and
    passing it as an argument or returning it, copies it.
    *Follows:* `run/objects_by_value`. *Breaks:*
    `error/mutating_call_on_parameter` (the copy a function receives is
    constant).
18. **Assignment through a chain needs every step to be mutable.** In
    `c.center.x = 1;`, `c` must be a `flex` variable and `center` and `x`
    `flex` fields. A parameter, a `🔒` variable or field, and the result
    of a call or `spawn` are not mutable.
    *Follows:* `run/struct_chains`. *Breaks:*
    `error/assign_constant_field`, `error/assign_through_constant_object`,
    `error/assign_through_constant_chain`.
19. **A member function is mutating when it assigns a field of its
    object, or calls a mutating member function on its object or on one of
    its fields. A mutating member function may be called only through a
    mutable chain.** Non-mutating member functions can be called on
    anything, including `🔒` objects.
    *Follows:* `run/member_functions`. *Breaks:*
    `error/mutating_call_on_constant`, `error/mutating_call_indirect`,
    `error/member_assigns_constant_field`.
20. **Name lookup inside a member function: the parameters and locals,
    then the fields of the object, then the top-level variables declared
    above the structure.** So a parameter named like a field hides the
    field, and a field named like a global hides the global. A call by
    name looks among the structure's member functions first, then the
    top-level functions.
    *Follows:* `run/name_lookup`. *Breaks:*
    `error/member_global_declared_below`.

### read and print

21. **`read()` is a `🔫`.** It reads one integer from standard input; if
    the input is not an integer (or has ended), it gives 0.
    *Follows:* `run/read_sum`, `run/point_read`. *Breaks:*
    `error/read_into_i64`.
22. **`print` takes an integer, a bool, an object or a string literal,
    and always ends with a newline.** Integers print in decimal, bools as
    `true` / `false`, string literals as written (escapes `\n`, `\t`,
    `\"`, `\\`). An object prints as its type and its fields in
    declaration order, with nested objects inline and no newline inside:
    `Circle { center: Point { x: 5, y: 15 }, r: 10 }`; an object with no
    fields prints as `Empty { }`. A string literal can appear only in
    `print`.
    *Follows:* `run/print_formats`. *Breaks:*
    `error/string_outside_print`.

## Code generation

`codegen.py` builds the module with `llvmlite.ir`; the `.ll` file is
`str(module)`, nothing else.

- Every function is declared before any body is generated. OWL functions
  are named `owl.<name>` and member functions `owl.<Struct>.<member>`, so
  an OWL function named `main` or `printf` does not clash with the C
  runtime. A member function's first parameter is a pointer to the
  object; a call passes the object's address.
- Each structure is an identified struct type `%"owl.<Name>"`. An object
  is an `alloca` of it; a field is reached with a `gep` by the field's
  index from the symbol table.
- Top-level variables are globals `owl.g.<name>`; locals and parameters
  are `alloca`s in the function's entry block.
- Checked `+! -! *!` use the `llvm.s{add,sub,mul}.with.overflow`
  intrinsics; a failed check calls a small runtime function that flushes
  stdout, writes the message to stderr and calls `exit(1)`.
- `printf` and `scanf` are only declared; clang links them from the C
  library. Format strings are private global constants. Printing an
  object walks the structure's field table and emits one `gep`, `load`
  and `printf` per field, so a new structure prints with no new compiler
  code.

## Project layout

```
lexer.py          hand-written byte-level lexer (state machine)
parser.py         recursive-descent parser, one function per grammar rule
ast_nodes.py      AST node classes and the --ast printer
semantic.py       semantic pass: symbol table, checks, AST annotations
codegen.py        LLVM IR generation with llvmlite.ir
compiler.py       command-line entry point
grammar.ebnf      the complete grammar
requirements.txt  Python dependencies
tests/            test programs and run_tests.py
```
