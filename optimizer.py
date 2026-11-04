"""The optimizer behind --optimize: three transformations of the checked tree,
run after semantic.py and before codegen.py, repeated until none changes
anything:

  unused functions   a function no reachable code calls is removed
  unused variables   a declaration nobody reads is removed with its assignments
  inlining           a function called exactly once replaces its call

The tree is already resolved, so every name carries the VarInfo or FuncInfo it
refers to. Scopes and shadowing need no work here: two variables with one name
are two VarInfo objects. README.md lists the shapes that are inlined.
"""

from collections import Counter

from ast_nodes import (
    ProgramNode, BlockNode, VarDeclNode, AssignNode, IfNode, ForNode, ParamNode, FieldDeclNode,
    IntLiteralNode, BoolLiteralNode, IdentNode, UnaryExprNode, BinaryExprNode,
    FunctionDeclNode, ReturnNode, ExprStmtNode, CallNode,
    StructDeclNode, FieldAssignNode, NewNode, FieldAccessNode, MethodCallNode,
    PrintNode, ReadNode, StringLiteralNode,
)
from semantic import VarInfo

# The search for a call site found code that must stay ahead of the call.
BLOCKED = object()


def _walk(node):
    """Every node under node, node included."""
    yield node
    for _, child in node.children():
        yield from _walk(child)


def _statement_lists(node):
    """Every list of statements under node, so a statement can be replaced."""
    if isinstance(node, (ProgramNode, BlockNode)):
        yield node.statements
    for _, child in node.children():
        yield from _statement_lists(child)


def _has_effects(expr):
    """True when evaluating expr does more than give a value: a call or read()
    must run, and division or a checked operator can stop the program."""
    for node in _walk(expr):
        if isinstance(node, (CallNode, MethodCallNode, ReadNode)):
            return True
        if isinstance(node, BinaryExprNode) and (node.checked or node.op == "DIV"):
            return True
    return False


def _chain_root(expr):
    while isinstance(expr, FieldAccessNode):
        expr = expr.obj
    return expr


class Optimizer:
    def __init__(self, program):
        self.program = program
        self.used_names = {node.name for node in _walk(program) if hasattr(node, "name")}
        self.renames = 0

    def run(self):
        changed = True
        while changed:
            changed = self._remove_unused_functions()
            changed = self._remove_unused_variables() or changed
            changed = self._inline_one_call() or changed

    # ---- unused functions --------------------------------------------

    def _top_level_code(self):
        return [s for s in self.program.statements if not isinstance(s, (FunctionDeclNode, StructDeclNode))]

    def _called_by(self, node):
        return {n.func for n in _walk(node) if isinstance(n, (CallNode, MethodCallNode))}

    def _remove_unused_functions(self):
        # Everything the top-level code can reach stays. Functions that only
        # call each other are not reached, so a removed body leaves nothing behind.
        reachable = set()
        work = [func for stmt in self._top_level_code() for func in self._called_by(stmt)]
        while work:
            func = work.pop()
            if func not in reachable:
                reachable.add(func)
                work.extend(self._called_by(func.node.body))

        changed = False
        kept = []
        for item in self.program.statements:
            if isinstance(item, FunctionDeclNode) and item.func not in reachable:
                changed = True
                continue
            kept.append(item)
        self.program.statements[:] = kept
        self.program.functions = [f for f in self.program.functions if f in reachable]

        for struct in self.program.structs:
            for name, method in list(struct.methods.items()):
                if method not in reachable:
                    del struct.methods[name]
                    struct.node.methods.remove(method.node)
                    changed = True
        return changed

    # ---- unused variables --------------------------------------------

    def _read_variables(self):
        reads = set()
        self._collect_reads(self.program, reads)
        return reads

    def _collect_reads(self, node, reads):
        if isinstance(node, FieldAssignNode) and isinstance(_chain_root(node.target), IdentNode):
            # Writing a field does not read the object the chain starts at.
            self._collect_reads(node.value, reads)
            return
        if isinstance(node, IdentNode) and isinstance(node.ref, VarInfo):
            reads.add(node.ref)
        for _, child in node.children():
            self._collect_reads(child, reads)

    def _dead_value(self, stmt, reads):
        """The expression stmt evaluates when stmt only stores into a variable
        nobody reads; None for every other statement."""
        if isinstance(stmt, VarDeclNode) and stmt.var not in reads:
            return stmt.value
        if isinstance(stmt, AssignNode) and isinstance(stmt.ref, VarInfo) and stmt.ref not in reads:
            return stmt.value
        if isinstance(stmt, FieldAssignNode):
            root = _chain_root(stmt.target)
            if isinstance(root, IdentNode) and isinstance(root.ref, VarInfo) and root.ref not in reads:
                return stmt.value
        return None

    def _remove_unused_variables(self):
        changed = False
        removed = True
        while removed:  # removing a declaration can leave another one unread
            removed = False
            reads = self._read_variables()
            for statements in _statement_lists(self.program):
                kept = []
                for stmt in statements:
                    value = self._dead_value(stmt, reads)
                    if value is None:
                        kept.append(stmt)
                        continue
                    removed = True
                    if _has_effects(value):
                        kept.append(ExprStmtNode(value, stmt.line, stmt.col))
                statements[:] = kept
            changed = changed or removed
        return changed

    # ---- inlining ----------------------------------------------------

    def _inline_candidates(self):
        counts = Counter(n.func for n in _walk(self.program) if isinstance(n, (CallNode, MethodCallNode)))
        return {func for func in self.program.functions
                if counts[func] == 1 and self._single_exit(func) and not self._is_recursive(func)}

    def _single_exit(self, func):
        # The only shape inlined: statements, then one gg as the last statement.
        statements = func.node.body.statements
        exits = [n for n in _walk(func.node.body) if isinstance(n, ReturnNode)]
        return len(exits) == 1 and statements[-1] is exits[0]

    def _is_recursive(self, func):
        seen = set()
        work = list(self._called_by(func.node.body))
        while work:
            callee = work.pop()
            if callee is func:
                return True
            if callee not in seen:
                seen.add(callee)
                work.extend(self._called_by(callee.node.body))
        return False

    def _inline_one_call(self):
        candidates = self._inline_candidates()
        if not candidates:
            return False
        for statements in _statement_lists(self.program):
            for index, stmt in enumerate(statements):
                site = self._find_call_site(stmt, candidates)
                if site is not None:
                    self._inline(site[0], site[1], statements, index)
                    return True
        return False

    def _find_call_site(self, stmt, candidates):
        """A candidate call in stmt that can move in front of stmt, with a
        function that puts a value in the call's place. A while condition is
        not searched: it runs again on every iteration."""
        if isinstance(stmt, (VarDeclNode, AssignNode, FieldAssignNode, ReturnNode)):
            places = ["value"]
        elif isinstance(stmt, PrintNode):
            places = [] if isinstance(stmt.value, StringLiteralNode) else ["value"]
        elif isinstance(stmt, ExprStmtNode):
            places = ["expr"]
        elif isinstance(stmt, IfNode):
            places = ["condition"]
        elif isinstance(stmt, ForNode):
            places = ["start", "end"]
        else:
            places = []
        for place in places:
            found = self._search(getattr(stmt, place), lambda v, p=place: setattr(stmt, p, v), candidates)
            if found is BLOCKED:
                return None
            if found is not None:
                return found
        return None

    def _search(self, expr, put, candidates):
        """Walks expr in evaluation order. Returns (call, put) for a candidate,
        BLOCKED when something evaluated before it could notice the move, and
        None when expr is safe to step over."""
        if isinstance(expr, (IntLiteralNode, BoolLiteralNode)):
            return None
        if isinstance(expr, IdentNode):
            # A call cannot change the caller's locals, but it can change a
            # global or, through a global object, a field.
            is_local = isinstance(expr.ref, VarInfo) and expr.ref.kind != "global"
            return None if is_local else BLOCKED
        if isinstance(expr, ReadNode):
            return BLOCKED
        if isinstance(expr, UnaryExprNode):
            return self._search(expr.operand, lambda v: setattr(expr, "operand", v), candidates)
        if isinstance(expr, FieldAccessNode):
            return self._search(expr.obj, lambda v: setattr(expr, "obj", v), candidates)
        if isinstance(expr, BinaryExprNode):
            found = self._search(expr.left, lambda v: setattr(expr, "left", v), candidates)
            if found is None:
                found = self._search(expr.right, lambda v: setattr(expr, "right", v), candidates)
            if found is None and (expr.checked or expr.op == "DIV"):
                return BLOCKED  # it could stop the program before a call to its right
            return found
        if isinstance(expr, NewNode):
            return self._search_args(expr.args, candidates)
        if isinstance(expr, CallNode):
            if expr.func in candidates:
                return expr, put
            return self._search_args(expr.args, candidates) or BLOCKED
        if isinstance(expr, MethodCallNode):
            found = self._search(expr.obj, lambda v: setattr(expr, "obj", v), candidates)
            return found or self._search_args(expr.args, candidates) or BLOCKED
        return BLOCKED

    def _search_args(self, args, candidates):
        for i, arg in enumerate(args):
            found = self._search(arg, lambda v, i=i: args.__setitem__(i, v), candidates)
            if found is not None:
                return found
        return None

    def _fresh_name(self, func_name, name):
        while True:
            self.renames += 1
            fresh = f"{func_name}_{name}_{self.renames}"
            if fresh not in self.used_names:
                self.used_names.add(fresh)
                return fresh

    def _rename_shadowed_globals(self, body):
        """A global the moved body uses must not read like a local or a field
        of its new surroundings, so it gets a new name everywhere."""
        shadowing = {n.name for n in _walk(self.program)
                     if isinstance(n, (ForNode, ParamNode, FieldDeclNode))
                     or (isinstance(n, VarDeclNode) and n.var.kind != "global")}
        used = {n.ref for n in _walk(body) if isinstance(n, (IdentNode, AssignNode)) and isinstance(n.ref, VarInfo)}
        for var in used:
            if var.kind == "global" and var.name in shadowing:
                var.name = self._fresh_name("global", var.name)
                for n in _walk(self.program):
                    if isinstance(n, VarDeclNode) and n.var is var:
                        n.name = var.name
                    elif isinstance(n, (IdentNode, AssignNode)) and n.ref is var:
                        n.name = var.name

    def _inline(self, call, put, statements, index):
        """Puts the body in front of the statement holding the call. The
        function goes away with this call, so its nodes are moved, not copied."""
        node = call.func.node
        moved = []
        for param, arg in zip(node.params, call.args):
            param.var.kind = "local"
            param.var.name = self._fresh_name(node.name, param.name)
            decl = VarDeclNode(False, param.var.name, param.param_type, param.type_pos, arg, param.line, param.col)
            decl.var = param.var
            moved.append(decl)
        for inner in _walk(node.body):
            if isinstance(inner, (VarDeclNode, ForNode)):
                inner.var.name = self._fresh_name(node.name, inner.name)
                inner.name = inner.var.name
        self._rename_shadowed_globals(node.body)
        for inner in _walk(node.body):
            if isinstance(inner, (IdentNode, AssignNode)) and isinstance(inner.ref, VarInfo):
                inner.name = inner.ref.name

        *body, exit_stmt = node.body.statements
        moved.extend(body)
        put(exit_stmt.value)
        stmt = statements[index]
        statements[index:index] = moved
        if isinstance(stmt, ExprStmtNode) and not _has_effects(stmt.expr):
            statements.remove(stmt)  # nothing uses the value of f(x);


def optimize(program):
    Optimizer(program).run()
    return program
