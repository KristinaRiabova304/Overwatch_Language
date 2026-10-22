"""AST node hierarchy for OWL and the --ast dump printer."""


class ASTNode:
    def __init__(self, line, col):
        self.line = line
        self.col = col

    def label(self):
        return self.__class__.__name__

    def children(self):
        """Return a list of (prefix, child_node) pairs. prefix is "" when the
        child needs no label (e.g. plain statement lists)."""
        return []


class ProgramNode(ASTNode):
    def __init__(self, statements, line=1, col=1):
        super().__init__(line, col)
        self.statements = statements

    def label(self):
        return "Program"

    def children(self):
        return [("", s) for s in self.statements]


class BlockNode(ASTNode):
    def __init__(self, statements, line, col):
        super().__init__(line, col)
        self.statements = statements

    def label(self):
        return "Block"

    def children(self):
        return [("", s) for s in self.statements]


class StmtNode(ASTNode):
    pass


class VarDeclNode(StmtNode):
    def __init__(self, mutable, name, var_type, type_pos, value, line, col):
        super().__init__(line, col)
        self.mutable = mutable
        self.name = name
        self.var_type = var_type
        self.type_pos = type_pos
        self.value = value

    def label(self):
        return f"VarDecl name={self.name} mutable={self.mutable} type={self.var_type}"

    def children(self):
        return [("", self.value)]


class AssignNode(StmtNode):
    def __init__(self, name, value, line, col):
        super().__init__(line, col)
        self.name = name
        self.value = value

    def label(self):
        return f"Assign name={self.name}"

    def children(self):
        return [("", self.value)]


class IfNode(StmtNode):
    def __init__(self, condition, then_block, else_block, line, col):
        super().__init__(line, col)
        self.condition = condition
        self.then_block = then_block
        self.else_block = else_block

    def label(self):
        return "If"

    def children(self):
        result = [("condition", self.condition), ("then", self.then_block)]
        if self.else_block is not None:
            result.append(("else", self.else_block))
        return result


class ParamNode(ASTNode):
    def __init__(self, name, param_type, type_pos, line, col):
        super().__init__(line, col)
        self.name = name
        self.param_type = param_type
        self.type_pos = type_pos

    def label(self):
        return f"Param name={self.name} type={self.param_type}"


class FunctionDeclNode(StmtNode):
    def __init__(self, name, params, result_type, type_pos, body, line, col):
        super().__init__(line, col)
        self.name = name
        self.params = params
        self.result_type = result_type
        self.type_pos = type_pos
        self.body = body

    def label(self):
        return f"FunctionDecl name={self.name} result={self.result_type}"

    def children(self):
        return [("param", p) for p in self.params] + [("body", self.body)]


class FieldDeclNode(ASTNode):
    def __init__(self, mutable, name, field_type, type_pos, line, col):
        super().__init__(line, col)
        self.mutable = mutable
        self.name = name
        self.field_type = field_type
        self.type_pos = type_pos

    def label(self):
        return f"Field name={self.name} mutable={self.mutable} type={self.field_type}"


class StructDeclNode(StmtNode):
    def __init__(self, name, fields, methods, line, col):
        super().__init__(line, col)
        self.name = name
        self.fields = fields
        self.methods = methods

    def label(self):
        return f"StructDecl name={self.name}"

    def children(self):
        return [("field", f) for f in self.fields] + [("method", m) for m in self.methods]


class FieldAssignNode(StmtNode):
    """Assignment through a chain: target is a FieldAccessNode."""

    def __init__(self, target, value, line, col):
        super().__init__(line, col)
        self.target = target
        self.value = value

    def label(self):
        return "FieldAssign"

    def children(self):
        return [("target", self.target), ("value", self.value)]


class ReturnNode(StmtNode):
    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value

    def label(self):
        return "Return"

    def children(self):
        return [("", self.value)]


class PrintNode(StmtNode):
    """print(value); value is an expression or a StringLiteralNode."""

    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value

    def label(self):
        return "Print"

    def children(self):
        return [("", self.value)]


class ExprStmtNode(StmtNode):
    """An expression used as a statement; its value is discarded."""

    def __init__(self, expr, line, col):
        super().__init__(line, col)
        self.expr = expr

    def label(self):
        return "ExprStmt"

    def children(self):
        return [("", self.expr)]


class ExprNode(ASTNode):
    pass


class CallNode(ExprNode):
    def __init__(self, name, args, line, col):
        super().__init__(line, col)
        self.name = name
        self.args = args

    def label(self):
        return f"Call name={self.name} args={len(self.args)}"

    def children(self):
        return [("arg", a) for a in self.args]


class NewNode(ExprNode):
    """spawn Name(args): creates an object with one value per field."""

    def __init__(self, struct_name, args, line, col):
        super().__init__(line, col)
        self.struct_name = struct_name
        self.args = args

    def label(self):
        return f"New type={self.struct_name} args={len(self.args)}"

    def children(self):
        return [("arg", a) for a in self.args]


class FieldAccessNode(ExprNode):
    def __init__(self, obj, field, line, col):
        super().__init__(line, col)
        self.obj = obj
        self.field = field

    def label(self):
        return f"FieldAccess field={self.field}"

    def children(self):
        return [("object", self.obj)]


class MethodCallNode(ExprNode):
    """A chain that ends in a member call: obj.name(args)."""

    def __init__(self, obj, name, args, line, col):
        super().__init__(line, col)
        self.obj = obj
        self.name = name
        self.args = args

    def label(self):
        return f"MethodCall name={self.name} args={len(self.args)}"

    def children(self):
        return [("object", self.obj)] + [("arg", a) for a in self.args]


class ReadNode(ExprNode):
    def label(self):
        return "Read"


class StringLiteralNode(ASTNode):
    """Not an expression: a string literal can only be printed."""

    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value

    def label(self):
        return f"StringLiteral value={self.value!r}"


class IntLiteralNode(ExprNode):
    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value

    def label(self):
        return f"IntLiteral value={self.value}"


class BoolLiteralNode(ExprNode):
    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value

    def label(self):
        return f"BoolLiteral value={self.value}"


class IdentNode(ExprNode):
    def __init__(self, name, line, col):
        super().__init__(line, col)
        self.name = name

    def label(self):
        return f"Ident name={self.name}"


class UnaryExprNode(ExprNode):
    def __init__(self, op, operand, line, col):
        super().__init__(line, col)
        self.op = op
        self.operand = operand

    def label(self):
        return f"UnaryExpr op={self.op}"

    def children(self):
        return [("", self.operand)]


class BinaryExprNode(ExprNode):
    def __init__(self, op, checked, left, right, line, col):
        super().__init__(line, col)
        self.op = op
        self.checked = checked
        self.left = left
        self.right = right

    def label(self):
        return f"BinaryExpr op={self.op} checked={self.checked}"

    def children(self):
        return [("left", self.left), ("right", self.right)]


def dump_ast(node, depth=0, prefix=""):
    """Render the AST as indented lines: one node per line, children indented
    by depth, with the mutability/type/operator fields inline in the label."""
    lines = []
    indent = "  " * depth
    head_prefix = f"{prefix}: " if prefix else ""
    lines.append(f"{indent}{head_prefix}{node.label()}")
    for child_prefix, child in node.children():
        lines.extend(dump_ast(child, depth + 1, child_prefix))
    return lines
