"""A small, safe formula language for alpha factors.

A formula is a Python-like expression over date x ticker panels, e.g.

    RANK(DELAY(CLOSE, 21) / DELAY(CLOSE, 252) - 1)

Formulas are parsed with `ast` and evaluated by walking the tree, never with
eval(), so a formula written by an LLM can only call the functions listed here.
Every function is causal (row t only uses rows <= t), so no formula can look
ahead, and windows must be positive integer literals. Window placeholders like
`{n}` are filled from a parameter grid before parsing.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from horizon_trader.features.price import rsi

Panel = pd.DataFrame
MAX_WINDOW = 2520  # ~10 years of trading days


class FormulaError(ValueError):
    pass


FIELDS: dict[str, str] = {
    "OPEN": "adjusted daily open",
    "HIGH": "adjusted daily high",
    "LOW": "adjusted daily low",
    "CLOSE": "adjusted daily close",
    "VOLUME": "daily share volume",
    "RETURNS": "daily close-to-close return",
    "DOLLAR_VOLUME": "CLOSE * VOLUME",
}


def _derive(name: str, data: dict[str, Panel]) -> Panel:
    if name == "RETURNS":
        return data["close"].pct_change()
    if name == "DOLLAR_VOLUME":
        return data["close"] * data["volume"]
    return data[name.lower()]


def _rank_cs(x: Panel) -> Panel:
    return x.rank(axis=1, pct=True)


def _zscore_cs(x: Panel) -> Panel:
    return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)


@dataclass(frozen=True)
class Function:
    impl: Callable[..., Panel]
    args: str  # one char per argument: "x" panel/number, "n" window
    doc: str


FUNCTIONS: dict[str, Function] = {
    "DELAY": Function(lambda x, n: x.shift(n), "xn", "value n days ago"),
    "DELTA": Function(lambda x, n: x - x.shift(n), "xn", "x minus its value n days ago"),
    "PCT_CHANGE": Function(lambda x, n: x / x.shift(n) - 1, "xn", "n-day percent change"),
    "MA": Function(lambda x, n: x.rolling(n).mean(), "xn", "n-day simple moving average"),
    "EMA": Function(
        lambda x, n: x.ewm(span=n, adjust=False, min_periods=n).mean(), "xn", "n-day EMA"
    ),
    "STD": Function(lambda x, n: x.rolling(n).std(), "xn", "n-day rolling standard deviation"),
    "SUM": Function(lambda x, n: x.rolling(n).sum(), "xn", "n-day rolling sum"),
    "TS_MAX": Function(lambda x, n: x.rolling(n).max(), "xn", "n-day rolling max"),
    "TS_MIN": Function(lambda x, n: x.rolling(n).min(), "xn", "n-day rolling min"),
    "TS_RANK": Function(
        lambda x, n: x.rolling(n).rank(pct=True), "xn", "percentile of today within last n days"
    ),
    "CORR": Function(lambda x, y, n: x.rolling(n).corr(y), "xxn", "n-day rolling correlation"),
    "RSI": Function(lambda x, n: rsi(x, n), "xn", "Wilder RSI (0-100)"),
    "RANK": Function(_rank_cs, "x", "cross-sectional percentile rank across stocks (0-1)"),
    "ZSCORE": Function(_zscore_cs, "x", "cross-sectional z-score across stocks"),
    "DEMEAN": Function(lambda x: x.sub(x.mean(axis=1), axis=0), "x", "minus cross-section mean"),
    "LOG": Function(lambda x: np.log(x.where(x > 0)), "x", "natural log (NaN if <= 0)"),
    "ABS": Function(lambda x: x.abs(), "x", "absolute value"),
    "SIGN": Function(np.sign, "x", "sign (-1, 0, 1)"),
}
ALIASES = {"SMA": "MA", "MAX": "TS_MAX", "MIN": "TS_MIN"}

_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}


def fill_params(formula: str, params: dict[str, int] | None = None) -> str:
    try:
        return formula.format(**(params or {}))
    except KeyError as e:
        raise FormulaError(f"no value for placeholder {e} in {formula!r}") from None


def _window(node: ast.expr, fn: str) -> int:
    if not (isinstance(node, ast.Constant) and type(node.value) is int):
        raise FormulaError(f"{fn}: window must be an integer literal, got {ast.unparse(node)!r}")
    if not 1 <= node.value <= MAX_WINDOW:
        raise FormulaError(f"{fn}: window must be between 1 and {MAX_WINDOW}, got {node.value}")
    return node.value


def _check(node: ast.expr) -> None:
    """Reject anything outside the language before evaluating."""
    match node:
        case ast.Constant(value=v) if type(v) in (int, float):
            return
        case ast.Name(id=name):
            if name not in FIELDS:
                raise FormulaError(f"unknown field {name!r}; fields: {', '.join(FIELDS)}")
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY:
            _check(left)
            _check(right)
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=operand):
            _check(operand)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]):
            fn_name = ALIASES.get(name, name)
            if fn_name not in FUNCTIONS:
                raise FormulaError(f"unknown function {name!r}")
            spec = FUNCTIONS[fn_name].args
            if len(args) != len(spec):
                raise FormulaError(f"{name} takes {len(spec)} argument(s), got {len(args)}")
            for arg, kind in zip(args, spec, strict=True):
                if kind == "n":
                    _window(arg, name)
                else:
                    _check(arg)
        case _:
            raise FormulaError(f"unsupported syntax: {ast.unparse(node)!r}")


def parse(formula: str) -> ast.expr:
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"syntax error in {formula!r}: {e.msg}") from None
    _check(tree.body)
    return tree.body


def fields_used(formula: str) -> set[str]:
    return {n.id for n in ast.walk(parse(formula)) if isinstance(n, ast.Name) and n.id in FIELDS}


def _eval(node: ast.expr, data: dict[str, Panel]):
    match node:
        case ast.Constant(value=v):
            return v
        case ast.Name(id=name):
            return _derive(name, data)
        case ast.BinOp(left=left, op=op, right=right):
            return _BINARY[type(op)](_eval(left, data), _eval(right, data))
        case ast.UnaryOp(op=op, operand=operand):
            value = _eval(operand, data)
            return -value if isinstance(op, ast.USub) else value
        case ast.Call(func=ast.Name(id=name), args=args):
            fn = FUNCTIONS[ALIASES.get(name, name)]
            values = [
                arg.value if kind == "n" else _eval(arg, data)
                for arg, kind in zip(args, fn.args, strict=True)
            ]
            return fn.impl(*values)
    raise FormulaError(f"cannot evaluate {ast.unparse(node)!r}")  # unreachable after _check


def evaluate(formula: str, data: dict[str, Panel]) -> Panel:
    """Evaluate a formula on {"open", "high", "low", "close", "volume"} panels."""
    result = _eval(parse(formula), data)
    if not isinstance(result, pd.DataFrame):
        raise FormulaError(f"{formula!r} is a constant, not a signal")
    return result.replace([np.inf, -np.inf], np.nan)


def _signature(name: str, fn: Function) -> str:
    """e.g. CORR(x, y, n): panel arguments are x, y, ...; windows are n."""
    args = ["n" if kind == "n" else "xyz"[i] for i, kind in enumerate(fn.args)]
    return f"{name}({', '.join(args)})"


def language_reference() -> str:
    """Human/LLM-readable spec of the language, generated from the registries above."""
    fields = "\n".join(f"  {k}: {v}" for k, v in FIELDS.items())
    fns = "\n".join(f"  {_signature(name, f)}: {f.doc}" for name, f in FUNCTIONS.items())
    aliases = ", ".join(f"{a} = {b}" for a, b in ALIASES.items())
    return (
        f"Fields (date x stock panels):\n{fields}\n"
        f"Functions (n = positive integer literal window, in trading days):\n{fns}\n"
        f"Aliases: {aliases}\n"
        "Operators: + - * / ** and unary minus; numeric literals.\n"
        "Window placeholders like {n} may be used and filled from a parameter grid.\n"
        "Every operator is causal: a formula can only see data up to the current day."
    )
