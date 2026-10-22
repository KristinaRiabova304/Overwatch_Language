"""LLVM IR generation for OWL through the llvmlite.ir builder API.

Runs after semantic.py, so every expression already carries its type (.ty)
and every name, field and call is resolved. The only IR text the compiler
writes is str(module) of the module built here.

Naming in the module:
  owl.<name>               a top-level function
  owl.<Struct>.<member>    a member function; its first parameter is a
                           pointer to the object
  owl.g.<name>             a top-level (global) variable
  owl.rt.*                 runtime helpers (overflow / division traps)
  main, printf, scanf, fflush, write, exit   the C entry point and C library
"""

import llvmlite.ir as ir
import llvmlite.binding as llvm

from ast_nodes import (
    VarDeclNode, AssignNode, IfNode,
    IntLiteralNode, BoolLiteralNode, IdentNode, UnaryExprNode, BinaryExprNode,
    FunctionDeclNode, ReturnNode, ExprStmtNode, CallNode,
    StructDeclNode, FieldAssignNode, NewNode, FieldAccessNode, MethodCallNode,
    PrintNode, ReadNode, StringLiteralNode,
)
from semantic import FieldInfo

I1 = ir.IntType(1)
I8 = ir.IntType(8)
I32 = ir.IntType(32)
I64 = ir.IntType(64)
I8P = I8.as_pointer()

PRIMITIVE_LLVM = {"i32": I32, "i64": I64, "bool": I1}
PRINTF_FORMAT = {"i32": "%d", "i64": "%lld"}

# Overflow intrinsics for the checked operators +! -! *!
OVERFLOW_INTRINSICS = {
    "ADD": "llvm.sadd.with.overflow",
    "SUB": "llvm.ssub.with.overflow",
    "MUL": "llvm.smul.with.overflow",
}


class CodeGen:
    def __init__(self, program):
        self.program = program
        self.module = ir.Module(name="owl")
        self.module.triple = llvm.get_default_triple()
        self.struct_types = {}   # structure name -> identified struct type
        self.struct_infos = {s.name: s for s in program.structs}
        self.functions = {}      # FuncInfo -> ir.Function
        self.vars = {}           # VarInfo -> pointer (alloca or global)
        self.strings = {}        # text -> global constant
        self.builder = None
        self.alloca_builder = None
        self.self_ptr = None     # the object pointer inside a member function

    # ---- module ------------------------------------------------------

    def generate(self):
        self._declare_runtime()
        self._declare_struct_types()
        self._declare_functions()
        self._generate_main()
        for func in self.program.functions:
            self._generate_function(func)
        for struct in self.program.structs:
            for method in struct.methods.values():
                self._generate_function(method)
        return self.module

    def _declare_runtime(self):
        c_type = ir.FunctionType(I32, [I8P], var_arg=True)  # int f(const char *fmt, ...)
        self.printf = ir.Function(self.module, c_type, name="printf")
        self.scanf = ir.Function(self.module, c_type, name="scanf")
        self.c_write = ir.Function(self.module, ir.FunctionType(I64, [I32, I8P, I64]), name="write")
        self.c_exit = ir.Function(self.module, ir.FunctionType(ir.VoidType(), [I32]), name="exit")
        self.c_fflush = ir.Function(self.module, ir.FunctionType(I32, [I8P]), name="fflush")
        self.trap_overflow = self._make_trap("owl.rt.overflow", "runtime error: integer overflow\n")
        self.trap_div_zero = self._make_trap("owl.rt.div_zero", "runtime error: division by zero\n")

    def _make_trap(self, name, message):
        """A function that writes message to stderr and exits with code 1.
        stdout is flushed first, so what the program printed before the
        error comes out before the message."""
        func = ir.Function(self.module, ir.FunctionType(ir.VoidType(), []), name=name)
        builder = ir.IRBuilder(func.append_basic_block("entry"))
        builder.call(self.c_fflush, [ir.Constant(I8P, None)])
        text = self._string_ptr(message, builder)
        builder.call(self.c_write, [I32(2), text, I64(len(message.encode("utf-8")))])
        builder.call(self.c_exit, [I32(1)])
        builder.unreachable()
        return func

    def _declare_struct_types(self):
        # Fields only refer to structures declared above, so the bodies can
        # be set in declaration order.
        for struct in self.program.structs:
            self.struct_types[struct.name] = self.module.context.get_identified_type(f"owl.{struct.name}")
        for struct in self.program.structs:
            field_types = [self._llvm_type(f.ty) for f in struct.fields.values()]
            self.struct_types[struct.name].set_body(*field_types)

    def _declare_functions(self):
        # Every function is declared before any body is generated, so a call
        # to a function defined later resolves.
        for func in self.program.functions:
            fn_type = ir.FunctionType(self._llvm_type(func.result),
                                      [self._llvm_type(t) for t in func.param_types])
            self.functions[func] = ir.Function(self.module, fn_type, name=f"owl.{func.name}")
        for struct in self.program.structs:
            obj_ptr = self.struct_types[struct.name].as_pointer()
            for method in struct.methods.values():
                fn_type = ir.FunctionType(self._llvm_type(method.result),
                                          [obj_ptr] + [self._llvm_type(t) for t in method.param_types])
                self.functions[method] = ir.Function(self.module, fn_type,
                                                     name=f"owl.{struct.name}.{method.name}")

    def _llvm_type(self, ty):
        if ty in PRIMITIVE_LLVM:
            return PRIMITIVE_LLVM[ty]
        return self.struct_types[ty]

    # ---- function bodies ---------------------------------------------

    def _start_function(self, ir_func):
        # Allocas go in a separate entry block, so every local has one slot
        # no matter where in the body it is declared.
        alloca_block = ir_func.append_basic_block("entry")
        body_block = ir_func.append_basic_block("body")
        self.alloca_builder = ir.IRBuilder(alloca_block)
        jump = self.alloca_builder.branch(body_block)
        self.alloca_builder.position_before(jump)
        self.builder = ir.IRBuilder(body_block)

    def _alloca(self, ty, name=""):
        return self.alloca_builder.alloca(self._llvm_type(ty), name=name)

    def _generate_main(self):
        main = ir.Function(self.module, ir.FunctionType(I32, []), name="main")
        self._start_function(main)
        self.self_ptr = None
        top_level = [s for s in self.program.statements
                     if not isinstance(s, (FunctionDeclNode, StructDeclNode))]
        self._gen_statements(top_level)
        if not self.builder.block.is_terminated:
            self.builder.ret(I32(0))  # no top-level gg: exit code 0

    def _generate_function(self, func):
        ir_func = self.functions[func]
        node = func.node
        self._start_function(ir_func)
        args = list(ir_func.args)
        if func.struct is not None:
            self.self_ptr = args.pop(0)
            self.self_ptr.name = "self"
        else:
            self.self_ptr = None
        for param, arg in zip(node.params, args):
            arg.name = param.name
            slot = self._alloca(param.param_type, param.name)
            self.builder.store(arg, slot)
            self.vars[param.var] = slot
        self._gen_statements(node.body.statements)
        if not self.builder.block.is_terminated:
            # The semantic pass proved every path ends in gg; this block is
            # only reached after an if/else whose branches both returned.
            self.builder.unreachable()

    # ---- statements --------------------------------------------------

    def _gen_statements(self, statements):
        for stmt in statements:
            self._gen_statement(stmt)

    def _gen_statement(self, stmt):
        b = self.builder
        if isinstance(stmt, VarDeclNode):
            value = self._gen_expr(stmt.value)
            if stmt.var.kind == "global":
                slot = ir.GlobalVariable(self.module, self._llvm_type(stmt.var_type), name=f"owl.g.{stmt.name}")
                slot.initializer = ir.Constant(slot.value_type, None)  # zero until the declaration runs
            else:
                slot = self._alloca(stmt.var_type, stmt.name)
            self.vars[stmt.var] = slot
            b.store(value, slot)

        elif isinstance(stmt, AssignNode):
            value = self._gen_expr(stmt.value)
            b.store(value, self._ref_address(stmt.ref))

        elif isinstance(stmt, FieldAssignNode):
            value = self._gen_expr(stmt.value)
            b.store(value, self._gen_address(stmt.target))

        elif isinstance(stmt, IfNode):
            self._gen_if(stmt)

        elif isinstance(stmt, ReturnNode):
            b.ret(self._gen_expr(stmt.value))

        elif isinstance(stmt, PrintNode):
            self._gen_print(stmt.value)

        elif isinstance(stmt, ExprStmtNode):
            self._gen_expr(stmt.expr)

    def _gen_if(self, stmt):
        b = self.builder
        cond = self._gen_expr(stmt.condition)
        then_block = b.append_basic_block("then")
        else_block = b.append_basic_block("else") if stmt.else_block else None
        end_block = b.append_basic_block("endif")
        b.cbranch(cond, then_block, else_block or end_block)

        b.position_at_end(then_block)
        self._gen_statements(stmt.then_block.statements)
        if not b.block.is_terminated:
            b.branch(end_block)

        if else_block is not None:
            b.position_at_end(else_block)
            self._gen_statements(stmt.else_block.statements)
            if not b.block.is_terminated:
                b.branch(end_block)

        b.position_at_end(end_block)

    # ---- addresses ---------------------------------------------------

    def _ref_address(self, ref):
        if isinstance(ref, FieldInfo):
            # A field named directly inside a member function: the object is
            # self, and the index comes from the symbol table.
            return self.builder.gep(self.self_ptr, [I32(0), I32(ref.index)], inbounds=True, name=ref.name)
        return self.vars[ref]

    def _gen_address(self, expr):
        """The address of an object or a field. A value that has no address
        (the result of a call or spawn) is stored in a temporary first."""
        if isinstance(expr, IdentNode):
            return self._ref_address(expr.ref)
        if isinstance(expr, FieldAccessNode):
            obj = self._gen_address(expr.obj)
            index = expr.field_info.index
            return self.builder.gep(obj, [I32(0), I32(index)], inbounds=True, name=expr.field)
        value = self._gen_expr(expr)
        slot = self._alloca(expr.ty, "tmp")
        self.builder.store(value, slot)
        return slot

    # ---- expressions -------------------------------------------------

    def _gen_expr(self, expr):
        b = self.builder
        if isinstance(expr, IntLiteralNode):
            return ir.Constant(self._llvm_type(expr.ty), expr.value)

        if isinstance(expr, BoolLiteralNode):
            return ir.Constant(I1, int(expr.value))

        if isinstance(expr, IdentNode):
            return b.load(self._ref_address(expr.ref), name=expr.name)

        if isinstance(expr, FieldAccessNode):
            return b.load(self._gen_address(expr), name=expr.field)

        if isinstance(expr, UnaryExprNode):
            if isinstance(expr.operand, IntLiteralNode):
                return ir.Constant(self._llvm_type(expr.ty), -expr.operand.value)
            return b.sub(ir.Constant(self._llvm_type(expr.ty), 0), self._gen_expr(expr.operand))

        if isinstance(expr, BinaryExprNode):
            return self._gen_binary(expr)

        if isinstance(expr, CallNode):
            args = [self._gen_expr(a) for a in expr.args]
            if expr.implicit_self:
                args.insert(0, self.self_ptr)
            return b.call(self.functions[expr.func], args)

        if isinstance(expr, MethodCallNode):
            obj = self._gen_address(expr.obj)  # a call passes the object's address
            args = [obj] + [self._gen_expr(a) for a in expr.args]
            return b.call(self.functions[expr.func], args)

        if isinstance(expr, NewNode):
            value = ir.Constant(self.struct_types[expr.struct.name], ir.Undefined)
            for index, arg in enumerate(expr.args):
                value = b.insert_value(value, self._gen_expr(arg), index)
            return value

        if isinstance(expr, ReadNode):
            # scanf gets a pointer; on input that is not an integer the slot
            # keeps its 0.
            slot = self._alloca("i32", "read")
            b.store(I32(0), slot)
            b.call(self.scanf, [self._string_ptr("%d"), slot])
            return b.load(slot)

        raise AssertionError(f"unsupported expression {expr.label()}")

    def _gen_binary(self, expr):
        b = self.builder
        left = self._gen_expr(expr.left)
        right = self._gen_expr(expr.right)

        if expr.op in ("EQ", "NEQ"):
            op = "==" if expr.op == "EQ" else "!="
            return b.icmp_signed(op, left, right)

        if expr.op == "DIV":
            return self._gen_div(left, right, expr.checked)

        if not expr.checked:
            # Unchecked arithmetic wraps around (two's complement).
            return {"ADD": b.add, "SUB": b.sub, "MUL": b.mul}[expr.op](left, right)

        pair = b.call(self._overflow_intrinsic(expr.op, left.type), [left, right])
        self._trap_if(b.extract_value(pair, 1), self.trap_overflow)
        return b.extract_value(pair, 0)

    def _overflow_intrinsic(self, op, ty):
        """llvm.s{add,sub,mul}.with.overflow.iN returns {iN result, i1 overflowed}.
        Declared by hand: llvmlite's declare_intrinsic does not know their
        result type."""
        name = f"{OVERFLOW_INTRINSICS[op]}.i{ty.width}"
        if name in self.module.globals:
            return self.module.globals[name]
        fn_type = ir.FunctionType(ir.LiteralStructType([ty, I1]), [ty, ty])
        return ir.Function(self.module, fn_type, name=name)

    def _gen_div(self, left, right, checked):
        b = self.builder
        zero = ir.Constant(left.type, 0)
        minus_one = ir.Constant(left.type, -1)
        self._trap_if(b.icmp_signed("==", right, zero), self.trap_div_zero)
        is_minus_one = b.icmp_signed("==", right, minus_one)
        if checked:
            # MIN / -1 does not fit: the only overflowing division.
            min_value = ir.Constant(left.type, -(1 << (left.type.width - 1)))
            overflow = b.and_(is_minus_one, b.icmp_signed("==", left, min_value))
            self._trap_if(overflow, self.trap_overflow)
            return b.sdiv(left, right)
        # Unchecked: x / -1 is computed as 0 - x, which wraps for MIN instead
        # of being undefined behaviour in sdiv.
        safe_right = b.select(is_minus_one, ir.Constant(left.type, 1), right)
        return b.select(is_minus_one, b.sub(zero, left), b.sdiv(left, safe_right))

    def _trap_if(self, condition, trap):
        b = self.builder
        trap_block = b.append_basic_block("trap")
        ok_block = b.append_basic_block("ok")
        b.cbranch(condition, trap_block, ok_block)
        b.position_at_end(trap_block)
        b.call(trap, [])
        b.unreachable()
        b.position_at_end(ok_block)

    # ---- print -------------------------------------------------------

    def _string_ptr(self, text, builder=None):
        """A pointer to a global constant holding text (NUL-terminated)."""
        builder = builder or self.builder
        if text not in self.strings:
            data = bytearray(text.encode("utf-8") + b"\0")
            glob = ir.GlobalVariable(self.module, ir.ArrayType(I8, len(data)), name=f"str.{len(self.strings)}")
            glob.initializer = ir.Constant(glob.value_type, data)
            glob.global_constant = True
            glob.linkage = "private"
            glob.unnamed_addr = True
            self.strings[text] = glob
        return builder.gep(self.strings[text], [I32(0), I32(0)], inbounds=True)

    def _printf(self, fmt, *args):
        self.builder.call(self.printf, [self._string_ptr(fmt)] + list(args))

    def _gen_print(self, value):
        # Rule: every print ends with a newline.
        if isinstance(value, StringLiteralNode):
            self._printf("%s\n", self._string_ptr(value.value))
            return
        if value.ty in self.struct_types:
            self._print_object(self._gen_address(value), value.ty, prefix="")
            self._printf("\n")
        else:
            self._print_primitive(self._gen_expr(value), value.ty, prefix="")
            self._printf("\n")

    def _print_primitive(self, value, ty, prefix):
        if ty == "bool":
            text = self.builder.select(value, self._string_ptr("true"), self._string_ptr("false"))
            self._printf(prefix + "%s", text)
        else:
            self._printf(prefix + PRINTF_FORMAT[ty], value)

    def _print_object(self, ptr, struct_name, prefix):
        """Prints Name { field: value, ... } by walking the structure's field
        table: one gep, load and printf per field, nested objects inline."""
        struct = self.struct_infos[struct_name]
        self._printf(prefix + struct.name + " {")
        for i, field in enumerate(struct.fields.values()):
            label = ("," if i else "") + " " + field.name + ": "
            field_ptr = self.builder.gep(ptr, [I32(0), I32(field.index)], inbounds=True, name=field.name)
            if field.ty in self.struct_types:
                self._print_object(field_ptr, field.ty, label)
            else:
                self._print_primitive(self.builder.load(field_ptr), field.ty, label)
        self._printf(" }")


def generate(program):
    return CodeGen(program).generate()
