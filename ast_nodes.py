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
    def __init__(self, mutable, name, var_type, value, line, col):
        super().__init__(line, col)
        self.mutable = mutable
        self.name = name
        self.var_type = var_type
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


class ExprNode(ASTNode):
    pass


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
