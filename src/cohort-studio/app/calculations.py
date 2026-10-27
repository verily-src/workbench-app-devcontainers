import ast
import math

import numpy as np
import pandas as pd


def parse(expression: str, columns) -> ast.AST:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 1000:
        raise ValueError("Enter an expression of at most 1,000 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError("Invalid calculation expression.") from None
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("Calculation expression is too complex.")
    names = set(columns)

    def validate(node, depth=0):
        if depth > 12:
            raise ValueError("Calculation expression is too deeply nested.")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            try: number = float(node.value)
            except (OverflowError, ValueError): raise ValueError("Constants must be finite numbers.") from None
            if not math.isfinite(number): raise ValueError("Constants must be finite numbers.")
        elif isinstance(node, ast.Name):
            if node.id not in names: raise ValueError(f"Unknown column: {node.id}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate(node.operand, depth + 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            validate(node.left, depth + 1); validate(node.right, depth + 1)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            function = node.func.id.lower()
            if function == "col" and len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                if node.args[0].value not in names: raise ValueError(f"Unknown column: {node.args[0].value}")
            elif function in {"abs", "sqrt", "ln"} and len(node.args) == 1:
                validate(node.args[0], depth + 1)
            elif function == "coalesce" and 2 <= len(node.args) <= 5:
                for arg in node.args: validate(arg, depth + 1)
            else: raise ValueError("Use abs, sqrt, ln, coalesce, or col with the supported arguments.")
        else:
            raise ValueError("Expression contains an unsupported operation.")
    validate(tree.body)
    return tree.body


def evaluate(node: ast.AST, frame: pd.DataFrame) -> pd.Series:
    def series(value):
        if isinstance(value, pd.Series): return value
        return pd.Series(value, index=frame.index, dtype="float64")
    def column(name):
        return pd.to_numeric(frame[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
    def run(part):
        if isinstance(part, ast.Constant): return float(part.value)
        if isinstance(part, ast.Name): return column(part.id)
        if isinstance(part, ast.UnaryOp):
            value = run(part.operand)
            return value if isinstance(part.op, ast.UAdd) else -value
        if isinstance(part, ast.BinOp):
            left, right = run(part.left), run(part.right)
            if isinstance(part.op, ast.Add): return left + right
            if isinstance(part.op, ast.Sub): return left - right
            if isinstance(part.op, ast.Mult): return left * right
            return series(left).div(series(right).replace(0, np.nan))
        function = part.func.id.lower()
        if function == "col": return column(part.args[0].value)
        values = [series(run(arg)) for arg in part.args]
        if function == "abs": return values[0].abs()
        if function == "sqrt": return np.sqrt(values[0].where(values[0] >= 0))
        if function == "ln": return np.log(values[0].where(values[0] > 0))
        result = values[0]
        for value in values[1:]: result = result.combine_first(value)
        return result
    with np.errstate(all="ignore"):
        return series(run(node)).replace([np.inf, -np.inf], np.nan)


def sql(node: ast.AST, column, number) -> str:
    def compile_node(part):
        if isinstance(part, ast.Constant): return number(float(part.value))
        if isinstance(part, ast.Name): return column(part.id)
        if isinstance(part, ast.UnaryOp):
            op = "+" if isinstance(part.op, ast.UAdd) else "-"
            return f"({op}({compile_node(part.operand)}))"
        if isinstance(part, ast.BinOp):
            left, right = compile_node(part.left), compile_node(part.right)
            operator = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(part.op)]
            if operator == "/": right = f"NULLIF(({right}), 0.0)"
            return f"(({left}) {operator} ({right}))"
        function = part.func.id.lower()
        if function == "col": return column(part.args[0].value)
        args = [compile_node(arg) for arg in part.args]
        if function == "abs": return f"ABS({args[0]})"
        if function == "sqrt": return f"CASE WHEN ({args[0]}) >= 0 THEN SQRT({args[0]}) END"
        if function == "ln": return f"CASE WHEN ({args[0]}) > 0 THEN LN({args[0]}) END"
        return f"COALESCE({', '.join(args)})"
    result = compile_node(node)
    if len(result) > 30000:
        raise ValueError("Calculation expression is too complex.")
    return result
