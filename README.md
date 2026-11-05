# OWL — Overwatch Workshop Language

A small statically-typed language themed after *Overwatch*: declarations,
types and operators are spelled with game-flavored keywords and emoji
instead of the usual `let`/`i32`/`==`. The compiler checks a program in a
separate semantic pass and generates LLVM IR through the `llvmlite.ir`
builder, which clang turns into an executable. Stage 3 adds loops, an
optimizer behind `--optimize`, and a real program,
[`programs/training_range.txt`](programs/training_range.txt).

The full grammar is in [`grammar.ebnf`](grammar.ebnf).

## Building and running

Requirements: Python 3.9+, [llvmlite](https://pypi.org/project/llvmlite/),
and clang and llc (any version that reads the IR llvmlite prints; tested with
llvmlite 0.49 and LLVM 23). llc is only needed for the native build of
[the real program](#the-real-program).

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

`--optimize`, anywhere on the command line, runs the optimizer before code
generation. Together with `--ast` it checks the program and prints the tree
after the optimizer:

```
python3 compiler.py --optimize program.txt program.ll
python3 compiler.py --optimize --ast program.txt
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
| `tests/optimize/` | `--optimize --ast` output equals `NAME.ast`; the program prints `NAME.expected` with and without the flag |
| `programs/`    | each recorded session prints its `.expected` exactly, with and without the flag |

Every `run` and `error` test also runs with `--optimize`. A `happy` test's tree
changes under the flag, so there the script checks that the program behaves
the same with and without it; the few `happy` programs that only parse must be
rejected the same way by both.

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
program instead. `🆚` is `==`, `🚫` is `!=`, and `<` and `>` compare integers;
comparisons do not chain.

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

### Loops

`🔁` repeats its body while the condition is `🔥`. `🔂` runs its body for every
integer from the start up to, but not including, the end. `🛑` leaves the
innermost loop. The rules are under [Loops](#loops-1) below.

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
   `{ }` block of an `if` or a loop is a scope. An inner block may declare a name
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

### Loops

The feature of Stage 3. Its tests are `run/loops_*`, `happy/loops_ast` and
`error/loops_*`. The keywords are emoji because emoji were never identifiers:
every program that was valid in Stage 2 is still valid.

23. **The condition of `🔁` is `ult`, checked before every iteration.** A
    false condition runs the body zero times.
    *Follows:* `run/loops_while`. *Breaks:* `error/loops_condition_not_bool`.
24. **`🔂 i: T = start..end` runs for `start <= i < end`.** `T` is `🔫` or `🚀`,
    and both bounds have that type. Both are evaluated once, start first,
    before the first iteration. A range whose start is not below its end runs
    zero times.
    *Follows:* `run/loops_for`. *Breaks:*
    `error/loops_for_variable_not_integer`, `error/loops_range_wrong_type`,
    `error/loops_range_without_dots`.
25. **The loop variable is constant, and exists only in the loop.** The body
    shares its scope, so the body cannot redeclare it; the bounds cannot use it.
    *Follows:* `run/loops_for`. *Breaks:* `error/loops_assign_to_for_variable`,
    `error/loops_variable_gone_after_loop`,
    `error/loops_redeclare_variable_in_body`.
26. **A loop body is a scope, and starts over on every iteration.** A variable
    declared in it is initialised again each time.
    *Follows:* `run/loops_nested`.
27. **`🛑` is only allowed inside a loop and leaves the innermost one.** A
    statement after it in the same block is an error.
    *Follows:* `run/loops_break`. *Breaks:* `error/loops_break_outside`,
    `error/loops_unreachable_after_break`.
28. **A loop never counts as ending every path through a function,** because
    its body may not run. `gg` inside a loop leaves the function as usual, but
    the function still needs a `gg` after the loop, even after `🔁 🔥`.
    *Follows:* `run/loops_in_functions`, `run/loops_exit_code`. *Breaks:*
    `error/loops_do_not_end_function`.
29. **`<` and `>` take two integers of the same type and give `ult`.**
    *Follows:* `run/loops_while`. *Breaks:* `error/loops_order_bools`.

Two example programs:

```
// Reads numbers until a 0, then prints their sum.
flex sum: 🔫 = 0;
flex n: 🔫 = read();
🔁 n 🚫 0 {
  sum = sum + n;
  n = read();
}
print(sum);
```

```
// A triangle of totals: a loop inside a loop whose body declares a variable.
🔂 row: 🔫 = 0..3 {
  flex total: 🔫 = 0;
  🔂 col: 🔫 = 0..row + 1 {
    if col 🆚 2 {
      🛑;
    }
    total = total + col;
  }
  print(total);
}
```

## Loops in the IR

The output of `🔂 i: 🔫 = 0..n { sum = sum + i; }` inside a function:

```llvm
for.cond:
  %"i.1" = load i32, i32* %"i"
  %".9" = load i32, i32* %"i.end"
  %".10" = icmp slt i32 %"i.1", %".9"
  br i1 %".10", label %"for.body", label %"for.end"
for.body:
  %"sum.1" = load i32, i32* %"sum"
  %"i.2" = load i32, i32* %"i"
  %".12" = add i32 %"sum.1", %"i.2"
  store i32 %".12", i32* %"sum"
  br label %"for.step"
for.step:
  %"i.3" = load i32, i32* %"i"
  %".15" = add i32 %"i.3", 1
  store i32 %".15", i32* %"i"
  br label %"for.cond"
for.end:
```

`for.cond` compares the variable with the end, which was computed once and kept
in its own slot `%"i.end"`, and goes either into the body or out of the loop to
`for.end`. `for.body` is the OWL body; a `🛑` in it would be a branch straight to
`for.end`. `for.step` adds one, and its last line is the back edge: a branch to a
block that came earlier, which is what makes this a loop.

## The optimizer

`optimizer.py` works on the checked tree, after the semantic pass and before
code generation. Every name in the tree already points at its variable or
function, so two variables with one name are never confused. Its three
transformations repeat until none of them changes anything. Its tests are in
`tests/optimize/`.

**Unused variables.** A declaration nobody reads is removed with its
assignments, including assignments to its fields, and the pass repeats because
that can leave another variable unread. A value with an effect stays as a bare
expression: a call, `read()`, and division or a checked operator, which can stop
the program. `x = x + 1;` counts as a read of `x`. Parameters and loop variables
are never removed.
*Tests:* `unused_variables_chain`, `unused_variables_effects`.

**Unused functions.** Whatever the top-level code can reach stays, so removing
a body can leave another function unused, and a recursive function or a pair
that only call each other is removed when nothing else calls them. Member
functions are removed the same way.
*Tests:* `unused_functions_chain`, `unused_functions_recursive`.

**Inlining.** A top-level function called exactly once replaces its call. The
body moves in front of the statement holding the call: each parameter becomes a
constant local initialised with its argument, the value of the final `gg` stands
where the call stood, and every local is renamed `<function>_<name>_<number>`. A
global the body uses is renamed too when a local, parameter or field anywhere in
the program has its name.
*Tests:* `inlining_simple`, `inlining_chain_and_loop`,
`inlining_left_alone`, `inlining_global_above_declaration`.

| Inlined | Left alone, and why |
|---------|---------------------|
| A body of statements with one `gg`, as its last statement. The body may hold `if`s and loops | A `gg` anywhere else, such as inside an `if` or a loop: leaving early would need a jump the tree cannot express |
| A call in a declaration, assignment, `gg`, `print`, call statement, `if` condition or the bounds of `🔂` | A call in a `🔁` condition: it runs on every iteration, but the moved body would run once |
| A call with only literals, locals and arithmetic that cannot stop the program evaluated before it | A call after anything else in the same statement, such as `g + f()` with a global `g`, `h() + f()` or `(a / b) + f()`: moving the call ahead would change what the program does |
| | A recursive function, directly or through other functions |
| | A member function |

Inlining `heal` in this program, without and with `--optimize`:

```
ability heal(hp: 🔫, amount: 🔫) -> 🔫 {
  gg hp + amount;
}
flex current: 🔫 = read();
print(heal(current, 5));
```

Before, `main` calls the function:

```llvm
  %"current" = load i32, i32* @"owl.g.current"
  %".8" = call i32 @"owl.heal"(i32 %"current", i32 5)
  %".9" = getelementptr inbounds [3 x i8], [3 x i8]* @"str.2", i32 0, i32 0
  %".10" = call i32 (i8*, ...) @"printf"(i8* %".9", i32 %".8")
```

After, `@"owl.heal"` is gone from the module and its work is in `main`, on locals
with new names:

```llvm
  %"current" = load i32, i32* @"owl.g.current"
  store i32 %"current", i32* %"heal_hp_1"
  store i32 5, i32* %"heal_amount_2"
  %"heal_hp_1.1" = load i32, i32* %"heal_hp_1"
  %"heal_amount_2.1" = load i32, i32* %"heal_amount_2"
  %".10" = add i32 %"heal_hp_1.1", %"heal_amount_2.1"
  %".11" = getelementptr inbounds [3 x i8], [3 x i8]* @"str.2", i32 0, i32 0
  %".12" = call i32 (i8*, ...) @"printf"(i8* %".11", i32 %".10")
```

## The real program

`programs/training_range.txt` is a shooting range you play from the keyboard.
You set up a practice bot with health and armor, then pick from a menu: fire a
burst, repair the bot, forecast how many shots it would take, or see its status.
It ends when the bot is destroyed or you leave. Every answer is one whole number.
It uses the structure `Bot` with member functions, the functions `ask_number`,
`shots_needed` and `percent`, and `read` and `print`. Loops carry the program: `🔁`
runs the menu, re-asks after a bad answer and counts shots in the forecast, while
`🔂` fires the burst, and `🛑` ends a burst when the bot goes down.

Build the native binary, then run the two recorded sessions:

```
python3 compiler.py programs/training_range.txt training_range.ll
llc -filetype=obj training_range.ll -o training_range.o
clang training_range.o -o training_range
./training_range < programs/training_range.in
./training_range < programs/training_range.session2.in
```

Run `./training_range` alone to play. The first session destroys the bot; the
second tries bad answers, repairs, forecasts and leaves from the menu.

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
  are `alloca`s in the function's entry block, so a variable declared in a
  loop body takes one slot, not one per iteration. Locals moved into top-level
  code by the optimizer are `alloca`s in `main`.
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
optimizer.py      the optimizer behind --optimize
codegen.py        LLVM IR generation with llvmlite.ir
compiler.py       command-line entry point
grammar.ebnf      the complete grammar
requirements.txt  Python dependencies
tests/            test programs and run_tests.py
programs/         the real program and its recorded sessions
```
