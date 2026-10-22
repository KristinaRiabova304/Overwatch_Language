"""Semantic analysis for OWL: a separate pass over the AST, run before code
generation. It builds the symbol table (variables, functions, structures),
checks every rule listed in README.md, and annotates the AST so that the
code generator never has to look a name up again:

  every expression   .ty      its type: "i32", "i64", "bool" or a structure name
  IdentNode          .ref     the VarInfo or FieldInfo the name resolved to
  AssignNode         .ref     the same, for the assignment target
  FieldAccessNode    .field_info  the FieldInfo (index, type, mutability)
  CallNode           .func    the FuncInfo; .implicit_self is True for a call
                              of a member function by name inside a member
  MethodCallNode     .func    the FuncInfo of the member function
  NewNode / StructDeclNode .struct  the StructInfo
  FunctionDeclNode   .func    the FuncInfo
  VarDeclNode        .var     the VarInfo it declares
  ProgramNode        .structs, .functions   the tables, in declaration order
"""

from ast_nodes import (
    ProgramNode, BlockNode, VarDeclNode, AssignNode, IfNode,
    IntLiteralNode, BoolLiteralNode, IdentNode, UnaryExprNode, BinaryExprNode,
    FunctionDeclNode, ReturnNode, ExprStmtNode, CallNode,
    StructDeclNode, FieldAssignNode, NewNode, FieldAccessNode, MethodCallNode,
    PrintNode, ReadNode, StringLiteralNode,
)

INT_TYPES = ("i32", "i64")
PRIMITIVE_TYPES = ("i32", "i64", "bool")
INT_RANGES = {
    "i32": (-(2 ** 31), 2 ** 31 - 1),
    "i64": (-(2 ** 63), 2 ** 63 - 1),
}

# Types are spelled in error messages the way the programmer writes them.
TYPE_SPELLING = {"i32": "🔫", "i64": "🚀", "bool": "ult"}


def spell(ty):
    return TYPE_SPELLING.get(ty, ty)


class SemanticError(Exception):
    def __init__(self, line, col, message):
        super().__init__(message)
        self.line = line
        self.col = col
        self.message = message


class VarInfo:
    """A variable or a parameter. kind is "global", "local" or "param"."""

    def __init__(self, name, ty, mutable, kind):
        self.name = name
        self.ty = ty
        self.mutable = mutable
        self.kind = kind


class FieldInfo:
    def __init__(self, name, ty, mutable, index, struct):
        self.name = name
        self.ty = ty
        self.mutable = mutable
        self.index = index
        self.struct = struct


class FuncInfo:
    """A top-level function (struct is None) or a member function."""

    def __init__(self, name, param_types, result, node, struct=None):
        self.name = name
        self.param_types = param_types
        self.result = result
        self.node = node
        self.struct = struct
        # Member functions only: True when the function assigns a field of
        # its object, directly or through a member function it calls.
        self.mutating = False


class StructInfo:
    def __init__(self, name, node):
        self.name = name
        self.node = node
        self.fields = {}    # name -> FieldInfo, in declaration order
        self.methods = {}   # name -> FuncInfo, in declaration order


class Chain:
    """What the semantic pass knows about the object a chain denotes:
    whether every step is mutable, and, inside a member function, whether
    the chain starts at one of the object's own fields."""

    def __init__(self, mutable, self_rooted, culprit=None):
        self.mutable = mutable
        self.self_rooted = self_rooted
        self.culprit = culprit  # (name, line, col) of the first constant step


class _PendingMemberCall:
    """A call of a member function whose mutability can only be judged once
    every member function is known to be mutating or not."""

    def __init__(self, callee, chain, caller, node):
        self.callee = callee
        self.chain = chain
        self.caller = caller
        self.node = node


class Analyzer:
    def __init__(self):
        self.structs = {}
        self.functions = {}
        self.scopes = []           # innermost last; each is name -> VarInfo
        self.globals = {}          # the top-level scope
        self.current_func = None   # FuncInfo being checked, None at top level
        self.current_struct = None
        self.pending_calls = []

    # ---- entry point -------------------------------------------------

    def analyze(self, program):
        self._collect_structs(program)
        self._collect_functions(program)
        self.scopes = [self.globals]
        self._check_statements(program.statements, top_level=True)
        self._resolve_mutating_members()
        program.structs = list(self.structs.values())
        program.functions = list(self.functions.values())
        return program

    # ---- declarations ------------------------------------------------

    def _collect_structs(self, program):
        # Rule: a field's type is a primitive or a structure declared above.
        all_names = {item.name for item in program.statements if isinstance(item, StructDeclNode)}
        for item in program.statements:
            if not isinstance(item, StructDeclNode):
                continue
            if item.name in self.structs:
                raise SemanticError(item.line, item.col, f"structure '{item.name}' is already declared")
            info = StructInfo(item.name, item)
            for index, field in enumerate(item.fields):
                if field.name in info.fields:
                    raise SemanticError(field.line, field.col,
                                        f"field '{field.name}' is already declared in '{item.name}'")
                if field.field_type == item.name:
                    raise SemanticError(*field.type_pos, f"structure '{item.name}' cannot contain itself")
                if field.field_type in all_names and field.field_type not in self.structs:
                    raise SemanticError(*field.type_pos,
                                        f"structure '{field.field_type}' must be declared before '{item.name}'")
                if field.field_type not in PRIMITIVE_TYPES and field.field_type not in self.structs:
                    raise SemanticError(*field.type_pos, f"unknown type '{field.field_type}'")
                info.fields[field.name] = FieldInfo(field.name, field.field_type, field.mutable, index, info)
            self.structs[item.name] = info
            item.struct = info

        for info in self.structs.values():
            for method in info.node.methods:
                if method.name in info.fields:
                    raise SemanticError(method.line, method.col,
                                        f"'{method.name}' is already a field of '{info.name}'")
                if method.name in info.methods:
                    raise SemanticError(method.line, method.col,
                                        f"member function '{method.name}' is already declared in '{info.name}'")
                func = self._make_func_info(method, info)
                info.methods[method.name] = func

    def _collect_functions(self, program):
        # Every function is known before any body is checked, so a function
        # may call itself and any function declared below it.
        for item in program.statements:
            if not isinstance(item, FunctionDeclNode):
                continue
            if item.name in self.functions:
                raise SemanticError(item.line, item.col, f"function '{item.name}' is already declared")
            if item.name in self.structs:
                raise SemanticError(item.line, item.col, f"'{item.name}' is already a structure")
            self.functions[item.name] = self._make_func_info(item, None)

    def _make_func_info(self, node, struct):
        seen = set()
        for param in node.params:
            if param.name in seen:
                raise SemanticError(param.line, param.col, f"parameter '{param.name}' is already declared")
            seen.add(param.name)
            self._check_type_exists(param.param_type, param.type_pos)
        self._check_type_exists(node.result_type, node.type_pos)
        info = FuncInfo(node.name, [p.param_type for p in node.params], node.result_type, node, struct)
        node.func = info
        return info

    def _check_type_exists(self, ty, pos):
        if ty not in PRIMITIVE_TYPES and ty not in self.structs:
            raise SemanticError(*pos, f"unknown type '{ty}'")

    # ---- scopes ------------------------------------------------------

    def _declare(self, name, info, line, col):
        scope = self.scopes[-1]
        if name in scope:
            raise SemanticError(line, col, f"'{name}' is already declared in this scope")
        scope[name] = info

    def _lookup_name(self, name, line, col):
        """Rule: inside a member function a name is looked up among the
        parameters and locals, then the fields of the object, then the
        globals declared above the structure. Elsewhere: locals and
        parameters, then globals declared above."""
        # self.scopes[0] is the snapshot of globals; locals come after it.
        for scope in reversed(self.scopes[1:]):
            if name in scope:
                return scope[name]
        if self.current_struct is not None and name in self.current_struct.fields:
            return self.current_struct.fields[name]
        if name in self.scopes[0]:
            return self.scopes[0][name]
        raise SemanticError(line, col, f"'{name}' is not declared")

    # ---- statements --------------------------------------------------

    def _check_statements(self, statements, top_level=False):
        """Checks a statement list and returns True when every path through
        it ends in gg."""
        returns = False
        for stmt in statements:
            if returns:
                raise SemanticError(stmt.line, stmt.col, "unreachable statement after 'gg'")
            if isinstance(stmt, FunctionDeclNode):
                self._check_function(stmt, None)
            elif isinstance(stmt, StructDeclNode):
                for method in stmt.methods:
                    self._check_function(method, stmt.struct)
            else:
                returns = self._check_statement(stmt)
        return returns

    def _check_block(self, block):
        self.scopes.append({})
        returns = self._check_statements(block.statements)
        self.scopes.pop()
        return returns

    def _check_function(self, node, struct):
        func = node.func
        saved = (self.scopes, self.current_func, self.current_struct)
        # Rule: a function sees the globals declared above it, so the body
        # gets a copy of the global scope as it is at this point.
        params = {}
        for param in node.params:
            var = VarInfo(param.name, param.param_type, False, "param")
            param.var = var
            params[param.name] = var
        # The body shares one scope with the parameters, so a local cannot
        # redeclare a parameter.
        self.scopes = [dict(self.globals), params]
        self.current_func = func
        self.current_struct = struct
        returns = self._check_statements(node.body.statements)
        if not returns:
            where = f"'{struct.name}.{node.name}'" if struct else f"'{node.name}'"
            raise SemanticError(node.line, node.col, f"function {where} can end without 'gg'")
        self.scopes, self.current_func, self.current_struct = saved

    def _check_statement(self, stmt):
        if isinstance(stmt, VarDeclNode):
            self._check_type_exists(stmt.var_type, stmt.type_pos)
            self._expect(stmt.value, stmt.var_type)
            kind = "global" if self.current_func is None and len(self.scopes) == 1 else "local"
            var = VarInfo(stmt.name, stmt.var_type, stmt.mutable, kind)
            stmt.var = var
            self._declare(stmt.name, var, stmt.line, stmt.col)
            return False

        if isinstance(stmt, AssignNode):
            ref = self._lookup_name(stmt.name, stmt.line, stmt.col)
            stmt.ref = ref
            if isinstance(ref, FieldInfo):
                if not ref.mutable:
                    raise SemanticError(stmt.line, stmt.col, f"cannot assign to constant field '{stmt.name}'")
                self.current_func.mutating = True
            elif ref.kind == "param":
                raise SemanticError(stmt.line, stmt.col, f"cannot assign to parameter '{stmt.name}'")
            elif not ref.mutable:
                raise SemanticError(stmt.line, stmt.col, f"cannot assign to constant '{stmt.name}'")
            self._expect(stmt.value, ref.ty)
            return False

        if isinstance(stmt, FieldAssignNode):
            target_ty = self._check_expr(stmt.target)
            chain = self._chain(stmt.target)
            if not chain.mutable:
                name, line, col = chain.culprit
                raise SemanticError(line, col, f"cannot assign through {_quote(name)}: it is not mutable")
            if chain.self_rooted:
                self.current_func.mutating = True
            self._expect(stmt.value, target_ty)
            return False

        if isinstance(stmt, IfNode):
            self._expect(stmt.condition, "bool", "the condition")
            then_returns = self._check_block(stmt.then_block)
            else_returns = self._check_block(stmt.else_block) if stmt.else_block else False
            return then_returns and else_returns

        if isinstance(stmt, ReturnNode):
            if self.current_func is None:
                # Rule: gg at the top level ends the program; its value is
                # the exit code.
                self._expect(stmt.value, "i32", "the exit code")
            else:
                self._expect(stmt.value, self.current_func.result,
                             f"'gg' in '{self.current_func.name}'")
            return True

        if isinstance(stmt, PrintNode):
            if not isinstance(stmt.value, StringLiteralNode):
                self._check_expr(stmt.value)
            return False

        if isinstance(stmt, ExprStmtNode):
            self._check_expr(stmt.expr)
            return False

        raise SemanticError(stmt.line, stmt.col, f"unsupported statement {stmt.label()}")

    # ---- expressions -------------------------------------------------

    def _expect(self, expr, ty, what=None):
        actual = self._check_expr(expr, ty)
        if actual != ty:
            what = what or "value"
            raise SemanticError(expr.line, expr.col,
                                f"{what} must be {spell(ty)} but found {spell(actual)}")
        return actual

    def _check_expr(self, expr, hint=None):
        ty = self._infer(expr, hint)
        expr.ty = ty
        return ty

    def _infer(self, expr, hint):
        if isinstance(expr, IntLiteralNode):
            # Rule: an integer literal takes the type it is used as.
            ty = hint if hint in INT_TYPES else "i32"
            self._check_range(expr.value, ty, expr)
            return ty

        if isinstance(expr, BoolLiteralNode):
            return "bool"

        if isinstance(expr, ReadNode):
            return "i32"

        if isinstance(expr, IdentNode):
            ref = self._lookup_name(expr.name, expr.line, expr.col)
            expr.ref = ref
            return ref.ty

        if isinstance(expr, UnaryExprNode):
            if isinstance(expr.operand, IntLiteralNode):
                # -2147483648 is a valid 🔫 even though 2147483648 is not.
                ty = hint if hint in INT_TYPES else "i32"
                self._check_range(-expr.operand.value, ty, expr.operand)
                expr.operand.ty = ty
                return ty
            ty = self._check_expr(expr.operand, hint)
            if ty not in INT_TYPES:
                raise SemanticError(expr.line, expr.col, f"cannot negate {spell(ty)}")
            return ty

        if isinstance(expr, BinaryExprNode):
            return self._infer_binary(expr, hint)

        if isinstance(expr, CallNode):
            return self._infer_call(expr)

        if isinstance(expr, MethodCallNode):
            obj_ty = self._check_expr(expr.obj)
            struct = self._struct_of(obj_ty, expr.obj)
            if expr.name not in struct.methods:
                raise SemanticError(expr.line, expr.col,
                                    f"structure '{struct.name}' has no member function '{expr.name}'")
            func = struct.methods[expr.name]
            expr.func = func
            self._check_args(func, expr.args, expr, f"{struct.name}.{expr.name}")
            self._note_member_call(func, self._chain(expr.obj), expr)
            return func.result

        if isinstance(expr, FieldAccessNode):
            obj_ty = self._check_expr(expr.obj)
            struct = self._struct_of(obj_ty, expr.obj)
            if expr.field not in struct.fields:
                raise SemanticError(expr.line, expr.col,
                                    f"structure '{struct.name}' has no field '{expr.field}'")
            expr.field_info = struct.fields[expr.field]
            return expr.field_info.ty

        if isinstance(expr, NewNode):
            if expr.struct_name not in self.structs:
                raise SemanticError(expr.line, expr.col, f"unknown structure '{expr.struct_name}'")
            struct = self.structs[expr.struct_name]
            expr.struct = struct
            fields = list(struct.fields.values())
            if len(expr.args) != len(fields):
                raise SemanticError(expr.line, expr.col,
                                    f"'{struct.name}' has {_count(len(fields), 'field')} "
                                    f"but 'spawn' got {_count(len(expr.args), 'value')}")
            for arg, field in zip(expr.args, fields):
                self._expect(arg, field.ty, f"field '{field.name}' of '{struct.name}'")
            return struct.name

        raise SemanticError(expr.line, expr.col, f"unsupported expression {expr.label()}")

    def _infer_binary(self, expr, hint):
        if expr.op in ("EQ", "NEQ"):
            left_ty, right_ty = self._check_operands(expr, None)
            if left_ty not in PRIMITIVE_TYPES:
                raise SemanticError(expr.line, expr.col, f"cannot compare {spell(left_ty)} values")
            return "bool"
        left_ty, right_ty = self._check_operands(expr, hint)
        if left_ty not in INT_TYPES:
            raise SemanticError(expr.line, expr.col, f"arithmetic needs integers but found {spell(left_ty)}")
        return left_ty

    def _check_operands(self, expr, hint):
        # Rule: both operands have the same type. A literal operand takes the
        # type of the other one, so the non-literal side is checked first.
        if _is_literal(expr.left) and not _is_literal(expr.right):
            right_ty = self._check_expr(expr.right, hint)
            left_ty = self._check_expr(expr.left, right_ty)
        else:
            left_ty = self._check_expr(expr.left, hint)
            right_ty = self._check_expr(expr.right, left_ty)
        if left_ty != right_ty:
            raise SemanticError(expr.line, expr.col,
                                f"operands must have the same type but found {spell(left_ty)} and {spell(right_ty)}")
        return left_ty, right_ty

    def _infer_call(self, expr):
        # Rule: inside a member function, a call by name looks among the
        # member functions of the structure first, then the top-level ones.
        expr.implicit_self = False
        if self.current_struct is not None and expr.name in self.current_struct.methods:
            func = self.current_struct.methods[expr.name]
            expr.implicit_self = True
            expr.func = func
            self._check_args(func, expr.args, expr, expr.name)
            self._note_member_call(func, Chain(True, True), expr)
            return func.result
        if expr.name not in self.functions:
            raise SemanticError(expr.line, expr.col, f"function '{expr.name}' is not declared")
        func = self.functions[expr.name]
        expr.func = func
        self._check_args(func, expr.args, expr, expr.name)
        return func.result

    def _check_args(self, func, args, call, shown_name):
        expected = len(func.param_types)
        if len(args) != expected:
            raise SemanticError(call.line, call.col,
                                f"'{shown_name}' takes {_count(expected, 'argument')} but got {len(args)}")
        for i, (arg, ty) in enumerate(zip(args, func.param_types), start=1):
            self._expect(arg, ty, f"argument {i} of '{shown_name}'")

    def _check_range(self, value, ty, node):
        low, high = INT_RANGES[ty]
        if not low <= value <= high:
            raise SemanticError(node.line, node.col, f"{value} does not fit in {spell(ty)}")

    def _struct_of(self, ty, node):
        if ty not in self.structs:
            raise SemanticError(node.line, node.col, f"{spell(ty)} has no fields or member functions")
        return self.structs[ty]

    # ---- mutability of chains ----------------------------------------

    def _chain(self, expr):
        """Rule: a chain is mutable when every step is: a flex variable, then
        flex fields. A parameter, a 🔒 variable or field, or the result of a
        call or spawn is constant."""
        if isinstance(expr, IdentNode):
            ref = expr.ref
            if isinstance(ref, FieldInfo):
                return Chain(ref.mutable, True, (ref.name, expr.line, expr.col))
            mutable = ref.mutable and ref.kind != "param"
            return Chain(mutable, False, (ref.name, expr.line, expr.col))
        if isinstance(expr, FieldAccessNode):
            inner = self._chain(expr.obj)
            if not inner.mutable:
                return inner
            field = expr.field_info
            return Chain(field.mutable, inner.self_rooted, (field.name, expr.line, expr.col))
        if isinstance(expr, NewNode):
            return Chain(False, False, ("a spawned object", expr.line, expr.col))
        return Chain(False, False, (f"the result of '{expr.name}'", expr.line, expr.col))

    def _note_member_call(self, callee, chain, node):
        caller = self.current_func if self.current_func and self.current_func.struct else None
        self.pending_calls.append(_PendingMemberCall(callee, chain, caller, node))

    def _resolve_mutating_members(self):
        # Rule: a member function is mutating when it assigns a field or
        # calls a mutating member function of its own object (by name, or
        # through one of its own flex fields). Iterate to a fixed point.
        changed = True
        while changed:
            changed = False
            for call in self.pending_calls:
                if (call.callee.mutating and call.chain.self_rooted and call.chain.mutable
                        and not call.caller.mutating):
                    call.caller.mutating = True
                    changed = True
        # Rule: a mutating member function is called only through a
        # mutable chain.
        for call in sorted(self.pending_calls, key=lambda c: (c.node.line, c.node.col)):
            if call.callee.mutating and not call.chain.mutable:
                name, line, col = call.chain.culprit
                raise SemanticError(line, col,
                                    f"cannot call mutating member function '{call.callee.name}' "
                                    f"on {_quote(name)}: it is not mutable")


def _count(n, noun):
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _quote(name):
    """Quotes a name in a message; descriptions such as "a spawned object"
    are left as they are."""
    return name if " " in name else f"'{name}'"


def _is_literal(expr):
    """True for an expression made only of integer literals, whose type is
    taken from the other operand."""
    if isinstance(expr, IntLiteralNode):
        return True
    if isinstance(expr, UnaryExprNode):
        return _is_literal(expr.operand)
    if isinstance(expr, BinaryExprNode) and expr.op not in ("EQ", "NEQ"):
        return _is_literal(expr.left) and _is_literal(expr.right)
    return False


def analyze(program):
    return Analyzer().analyze(program)
