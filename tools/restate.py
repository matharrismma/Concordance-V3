"""Restatements that provably keep a claim's meaning, each judged by an oracle that calls no verifier
(run 2026-11-03-restatement-audit, step restate-registry: measurement 4 of the TRM report).

A claim restated in a way that keeps its meaning must get the same verdict; tools/restatement_audit.py (a later
step) compares the verdicts. This module only restates and judges. It imports nothing from concordance.verifiers
or concordance.derivation (tests/test_restate.py pins that in a fresh interpreter), and it never runs a verifier:
each oracle decides preservation from the claim's bytes alone.

    R1  key order        every object's keys in reverse order, at every depth, for every domain.
                         Oracle: validate.canonical_json_bytes equal, and the same values of the same types.
    R2  equality swap    an equality's expr_a and expr_b exchanged (mathematics, mode equality).
                         Oracle: the two parsed sides exchanged, everything else unchanged.
    R3  whitespace       one space inserted between every two adjacent tokens of each expression string of a
                         mapped mathematics mode. Oracle: the token sequence and the parse tree unchanged, only
                         spaces inserted, only between tokens (never inside **, 1e5 or a name), and declined when
                         the params come within 10% of derivation.py's size guard.
    R4  symbol rename    every free symbol of a mapped mathematics mode renamed to a fresh v0, v1, ..., with every
                         symbol-naming parameter renamed alike: variable (written in when the mode defaulted it),
                         variables, the system mode's claimed_solution keys. Oracle: the parse trees equal under
                         the symbol map it infers, the old names plain symbols, the new names fresh and drawn from
                         v<digits>, each of which sympify returns as a plain Symbol of that name. Both R4 and its
                         oracle map only expressions in which nothing but a bare name can name a symbol (R4_SHAPE):
                         no string (Symbol('x') names x where the rename cannot see it), no attribute or subscript,
                         and no call but to R4_FUNCTIONS; anything else is declined, whatever the verifier's own
                         guard would do with it.
    R5  step ids         every step id renamed to a fresh r0, r1, ... (a CLOSURE audit: verifiers never see ids),
                         by str(id), a falsy id read as its default s{i} and given an explicit id, every carrier of
                         a repeated id renamed alike, uses, bind sources and a document's {step_id} text rewritten.
                         Oracle: the dependency graph isomorphic under the id map, no collision made or undone,
                         no new id holding '.'.

A subject is a derivation (a list of steps) or a document (a dict whose "steps" is a list). restate(key, subject)
returns an Outcome: applied with the restated subject, or declined with the reason. A restatement never mutates
its input, is deterministic (no set or hash order reaches its output), declines whatever it cannot show is kept,
and returns nothing its own oracle refuses.

R2-R4 restate only steps the verifier routes to the {mode, params} form (domain mathematics or math, no
MATH_VERIFY key; a MATH_VERIFY packet is dispatched by its keys, not by a mode, and is declined), only modes in
MODES, and only steps that neither bind nor are bound from: their output data can carry a side, a spacing or a
symbol name into the step that binds it.

MODES and DEFAULT_VARIABLE are a second copy of what mathematics.py reads; tests/test_restate.py reads
mathematics.py and derivation.py as text (never imports them) and fails when the two drift.
"""
from __future__ import annotations

import ast
import copy
import functools
import io
import json
import os
import re
import sys
import tokenize
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from concordance.validate import canonical_json_bytes  # noqa: E402  (stdlib and jsonschema only; no verifier)

# ── what mathematics.py reads, per {mode, params} mode R2-R4 map ─────────────────────────────────────────────────
EXPR = "expression"              # one expression string (or a number)
EQUATION = "equation"            # "lhs = rhs", split at the first '=' as the verifier splits it, or one expression
EXPR_LIST = "expression list"    # a list of expressions
EQUATION_LIST = "equation list"  # a list of equations
SOLUTION = "solution"            # {symbol name: expression}
VARIABLE = "variable"            # one symbol name, with the mode's default when absent
NAMES = "names"                  # a list of symbol names, or {} (no names)
OTHER = "other"                  # read, names no symbol, never changed

MODES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    mode: MappingProxyType(fields) for mode, fields in {
        "equality": {"expr_a": EXPR, "expr_b": EXPR, "variables": NAMES, "claimed_literal": OTHER, "hedged": OTHER},
        "derivative": {"function": EXPR, "variable": VARIABLE, "claimed_derivative": EXPR},
        "integral": {"integrand": EXPR, "variable": VARIABLE, "claimed_antiderivative": EXPR},
        "limit": {"function": EXPR, "variable": VARIABLE, "point": EXPR, "claimed_limit": EXPR},
        "solve": {"equation": EQUATION, "variable": VARIABLE, "claimed_solutions": EXPR_LIST},
        # verify_inequality never reads variables; every benchmark inequality carries "variables": {}
        "inequality": {"lhs": EXPR, "rhs": EXPR, "op": OTHER, "variable": VARIABLE, "domain": OTHER,
                       "variables": NAMES},
        "system": {"equations": EQUATION_LIST, "claimed_solution": SOLUTION, "variables": NAMES},
    }.items()})
# spec.get("variable", "x") in verify_derivative, verify_integral, verify_limit, verify_solve, verify_inequality
DEFAULT_VARIABLE: Mapping[str, str] = MappingProxyType(
    {"derivative": "x", "integral": "x", "limit": "x", "solve": "x", "inequality": "x"})
# derivation.py: _MAX_SPEC_CHARS = int(os.environ.get("CONCORDANCE_MAX_EXPR_CHARS", "4000") or 4000), applied to
# len(json.dumps(params, default=str)) before any math verifier runs
SIZE_ENV, SIZE_DEFAULT = "CONCORDANCE_MAX_EXPR_CHARS", 4000
NEAR = 0.9                        # R3 and R4 decline params that come within 10% of the guard
NEW_NAME = re.compile(r"v[0-9]+")  # R4's fixed pattern
NEW_ID = re.compile(r"r[0-9]+")    # R5's fixed pattern
_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_KEPT_NAMES = frozenset({"oo", "inf"})   # mathematics._parse binds both to infinity unless a variable names them
_BRACE = re.compile(r"\{([^{}]*)\}")     # a document's {step_id} reference
_MATH_DOMAINS = ("mathematics", "math")

# R4 renames a symbol only where a bare name (an ast.Name) names it. A string names one too (Symbol('x'), S('x'),
# symbols('x')), and so can any string a call or an attribute computes (Symbol(chr(120))), so R4 and its oracle map
# only expressions built from numbers, names, operators, comparisons, tuples, lists and calls to these functions of
# numbers and symbols, none of which takes a name from a string or returns a string. Without a string literal,
# attribute or other call, no string exists while the expression is read, so no symbol is named but by a bare name.
# This is R4's own rule, not a copy of mathematics.py's guard (which refuses strings today): the oracle never leans
# on the verifier refusing what it cannot see.
R4_FUNCTIONS = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "acot", "asec", "acsc", "atan2", "sinc",
    "sinh", "cosh", "tanh", "coth", "sech", "csch", "asinh", "acosh", "atanh", "acoth",
    "exp", "log", "ln", "sqrt", "cbrt", "root", "Pow",
    "Abs", "abs", "sign", "floor", "ceiling", "frac",
    "factorial", "factorial2", "binomial", "gcd", "lcm", "Mod",
    "gamma", "loggamma", "polygamma", "digamma", "beta", "erf", "erfc", "erfi", "zeta",
    "Min", "Max", "re", "im", "conjugate", "arg",
    "Eq", "Ne", "Lt", "Le", "Gt", "Ge",
    "diff", "Derivative", "integrate", "Integral", "limit", "Limit", "Sum", "Product",
    "simplify", "expand", "factor", "cancel", "together", "apart", "Rational", "Integer",
})
R4_SHAPE = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
            ast.Call, ast.keyword, ast.Tuple, ast.List, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)
_STRING_NODES = tuple(getattr(ast, n) for n in ("JoinedStr", "TemplateStr") if hasattr(ast, n))


class Decline(Exception):
    """Preservation cannot be shown; the message says why."""


class Outcome:
    """One restatement of one subject: applied (after, mapping, restated) or declined (reason)."""
    __slots__ = ("key", "after", "reason", "mapping", "restated")

    def __init__(self, key: str, after: Any = None, reason: Optional[str] = None,
                 mapping: Optional[Dict[Any, Any]] = None, restated: Tuple[int, ...] = ()) -> None:
        self.key = key
        self.after = after          # the restated subject, when applied
        self.reason = reason        # why it declined, when it did
        self.mapping = mapping      # R4: {step index: {old name: new name}}; R5: {old id: new id}
        self.restated = restated    # the indices of the steps whose bytes changed

    @property
    def applied(self) -> bool:
        return self.reason is None

    def __repr__(self) -> str:
        return (f"Outcome({self.key}, applied, restated={self.restated})" if self.applied
                else f"Outcome({self.key}, declined: {self.reason})")


class Restatement:
    """One entry of the fixed registry: its key, its name, what it reaches, how it is built, its oracle."""
    __slots__ = ("key", "name", "reaches", "build", "oracle")

    def __init__(self, key: str, name: str, reaches: str,
                 build: Callable[[Any], Tuple[Any, Optional[Dict[Any, Any]], Tuple[int, ...]]],
                 oracle: Callable[[Any, Any], Optional[str]]) -> None:
        self.key, self.name, self.reaches, self.build, self.oracle = key, name, reaches, build, oracle

    def __repr__(self) -> str:
        return f"Restatement({self.key}, {self.name!r})"


# ── shared helpers ────────────────────────────────────────────────────────────────────────────────────────────
def _wire(obj: Any) -> str:
    """The bytes a caller would send, in the order given."""
    return json.dumps(obj, ensure_ascii=False)


def _same(a: Any, b: Any) -> bool:
    """Exactly the same values of exactly the same types, key order aside (canonical JSON cannot tell a tuple from
    a list, or the key 1 from the key "1")."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        tag = lambda k: (type(k).__name__, repr(k))  # noqa: E731
        if sorted(map(tag, a)) != sorted(map(tag, b)):
            return False
        return all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        return repr(a) == repr(b)
    return a == b


def _subject(subject: Any) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(steps, document or None), or Decline."""
    if isinstance(subject, list):
        steps, doc = subject, None
    elif isinstance(subject, dict) and isinstance(subject.get("steps"), list):
        steps, doc = subject["steps"], subject
    else:
        raise Decline("not a derivation (a list of steps) or a document (a dict whose steps is a list)")
    if not steps:
        raise Decline("no steps")
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            raise Decline(f"step {i} is not an object")
    try:
        _wire(subject)
    except (TypeError, ValueError) as e:
        raise Decline(f"not JSON: {e}")
    return steps, doc


def _rebuild(subject: Any, steps: List[Dict[str, Any]], **doc_fields: Any) -> Any:
    """The subject with its steps replaced (and, for a document, the named fields), in its own key order."""
    if isinstance(subject, list):
        return steps
    out = {}
    for k, v in subject.items():
        out[k] = steps if k == "steps" else (doc_fields[k] if k in doc_fields else copy.deepcopy(v))
    return out


def _effective_ids(steps: List[Dict[str, Any]]) -> List[str]:
    """derivation.verify_derivation's ids: str(id), a falsy id read as s{i}."""
    return [str(s.get("id") or f"s{i}") for i, s in enumerate(steps)]


def _bind_items(step: Dict[str, Any]) -> List[Tuple[Any, Any]]:
    bind = step.get("bind")
    return list(bind.items()) if isinstance(bind, dict) and bind else []


def _bind_sources(steps: List[Dict[str, Any]]) -> List[str]:
    return [str(ref).partition(".")[0] for s in steps for _, ref in _bind_items(s)]


def _spec_limit() -> int:
    try:
        return int(os.environ.get(SIZE_ENV, str(SIZE_DEFAULT)) or SIZE_DEFAULT)
    except ValueError:
        return SIZE_DEFAULT


def _size_reason(before: Dict[str, Any], after: Dict[str, Any]) -> Optional[str]:
    limit = _spec_limit()
    b, a = len(json.dumps(before, default=str)), len(json.dumps(after, default=str))
    if b > limit:
        return f"the params are already {b} characters, past the {limit}-character guard"
    if a > NEAR * limit:
        return f"the restated params would be {a} characters, within 10% of the {limit}-character guard"
    return None


def _norm(v: Any) -> str:
    return str(v if v is not None else "").strip().lower()


def _math_step(step: Dict[str, Any]) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    """(spec, mode, params) for a step the verifier routes to the {mode, params} form of a mapped mode, or Decline."""
    if _norm(step.get("domain", "")) not in _MATH_DOMAINS:
        raise Decline("not mathematics")
    spec = step.get("spec")
    if not isinstance(spec, dict):
        raise Decline("its spec is not an object")
    if "MATH_VERIFY" in spec:
        raise Decline("a MATH_VERIFY packet is dispatched by its keys (mathematics.py _RULES), not by a mode")
    mode = _norm(spec.get("mode"))
    if mode not in MODES:
        raise Decline(f"mode {mode!r} is not mapped")
    params = spec.get("params")
    if not isinstance(params, dict):
        raise Decline("its params are not an object")
    return spec, mode, params


def _flows(steps: List[Dict[str, Any]]) -> List[Optional[str]]:
    """Per step, why its output can reach another step's input (or its input comes from one), or None."""
    sources = set(_bind_sources(steps))
    return [("it binds an input from another step" if s.get("bind") else
             "another step binds from it" if sid in sources else None)
            for s, sid in zip(steps, _effective_ids(steps))]


def _per_step(subject: Any, step_fn: Callable[[str, Dict[str, Any]], Dict[str, Any]], only: Optional[str] = None,
              ) -> Tuple[Any, Dict[int, Any], Tuple[int, ...]]:
    """Run step_fn(mode, params) -> (new params, info) on every eligible step; Decline when none is restated."""
    steps, _ = _subject(subject)
    flows = _flows(steps)
    out, infos, done, why = [], {}, [], {}
    for i, step in enumerate(steps):
        try:
            spec, mode, params = _math_step(step)
            if only and mode != only:
                raise Decline(f"mode {mode!r} is not {only}")
            if flows[i]:
                raise Decline(flows[i])
            new_params, info = step_fn(mode, params)
            if _wire(new_params) == _wire(params):
                raise Decline("it changes no byte of this step")
        except Decline as d:
            why.setdefault(str(d), []).append(i)
            out.append(copy.deepcopy(step))
            continue
        new_spec = {k: (new_params if k == "params" else copy.deepcopy(v)) for k, v in spec.items()}
        out.append({k: (new_spec if k == "spec" else copy.deepcopy(v)) for k, v in step.items()})
        infos[i] = info
        done.append(i)
    if not done:
        raise Decline("no step restated: " + "; ".join(
            f"{r} (step{'s' if len(ix) > 1 else ''} {', '.join(map(str, ix[:3]))}{', ...' if len(ix) > 3 else ''})"
            for r, ix in why.items()))
    return _rebuild(subject, out), infos, tuple(done)


def _step_oracle(before: Any, after: Any, judge: Callable[[str, Dict[str, Any], Dict[str, Any]], Optional[str]],
                 only: Optional[str] = None) -> Optional[str]:
    """The frame every R2-R4 oracle shares: the same steps, a changed step eligible and changed only in its params,
    which judge(mode, before params, after params) must pass."""
    try:
        sb, db = _subject(before)
        sa, da = _subject(after)
    except Decline as d:
        return str(d)
    if (db is None) != (da is None) or len(sb) != len(sa):
        return "the subject's form or its number of steps changed"
    if db is not None and not _same({k: v for k, v in db.items() if k != "steps"},
                                    {k: v for k, v in da.items() if k != "steps"}):
        return "a document field outside its steps changed"
    flows = _flows(sb)
    for i, (b, a) in enumerate(zip(sb, sa)):
        if _same(b, a):
            continue
        try:
            spec_b, mode, params_b = _math_step(b)
            if only and mode != only:
                raise Decline(f"mode {mode!r} is not {only}")
            if flows[i]:
                raise Decline(flows[i])
        except Decline as d:
            return f"step {i} changed, but {d}"
        rest = lambda s: {k: v for k, v in s.items() if k != "spec"}  # noqa: E731
        spec_a = a.get("spec")
        if not _same(rest(b), rest(a)) or not isinstance(spec_a, dict) or not _same(
                {k: v for k, v in spec_b.items() if k != "params"}, {k: v for k, v in spec_a.items() if k != "params"}):
            return f"step {i} changed outside its params"
        params_a = spec_a.get("params")
        if not isinstance(params_a, dict):
            return f"step {i}'s params are no longer an object"
        why = judge(mode, params_b, params_a)
        if why:
            return f"step {i}: {why}"
    return None


# ── parsing an expression as mathematics._parse would see it, without running it ────────────────────────────────
def _core(s: str) -> Tuple[str, str, str]:
    """(leading whitespace, the stripped expression, trailing whitespace)."""
    core = s.strip()
    lead = s[:len(s) - len(s.lstrip())]
    return lead, core, s[len(lead) + len(core):]


def _tree(piece: str) -> ast.Expression:
    """The parse of one expression piece, or Decline: ASCII, one line, parseable as a Python expression."""
    if not piece.isascii():
        raise Decline("a non-ASCII expression")
    if "\n" in piece or "\r" in piece:
        raise Decline("an expression spanning lines")
    try:
        return ast.parse(piece.strip(), mode="eval")
    except SyntaxError:
        raise Decline(f"{piece.strip()!r} does not parse as an expression")


def _pieces(role: str, s: str) -> List[str]:
    """The pieces the verifier parses: an equation splits at its first '=' (verify_solve, verify_system)."""
    if role == EQUATION:
        if "==" in s:
            raise Decline("an equation holding '==' (solve and system read it differently)")
        if "=" in s:
            lhs, _, rhs = s.partition("=")
            return [lhs, rhs]
    return [s]


def _join(role: str, pieces: List[str]) -> str:
    return "=".join(pieces) if role == EQUATION else pieces[0]


def _values(role: str, value: Any) -> Iterator[Tuple[str, Any]]:
    """(scalar role, value) for every expression a field holds."""
    if role in (EXPR, EQUATION):
        yield role, value
    elif role in (EXPR_LIST, EQUATION_LIST):
        if not isinstance(value, list):
            raise Decline(f"a {role} that is not a list")
        for v in value:
            yield (EXPR if role == EXPR_LIST else EQUATION), v
    elif role == SOLUTION:
        if not isinstance(value, dict):
            raise Decline("a claimed_solution that is not an object")
        for v in value.values():
            yield EXPR, v


def _scalar(value: Any) -> bool:
    """A value the verifier reads through str() that holds no name: a number, a bool or None."""
    return value is None or isinstance(value, (int, float, bool))


def _map_field(role: str, value: Any, fn: Callable[[str, str], str]) -> Any:
    """The field with fn(scalar role, string) applied to every expression string it holds."""
    def one(r: str, v: Any) -> Any:
        if isinstance(v, str):
            return fn(r, v)
        if _scalar(v):
            return v
        raise Decline(f"an expression that is neither a string nor a number ({type(v).__name__})")
    if role in (EXPR, EQUATION):
        return one(role, value)
    if role in (EXPR_LIST, EQUATION_LIST):
        list(_values(role, value))
        return [one(EXPR if role == EXPR_LIST else EQUATION, v) for v in value]
    if role == SOLUTION:
        list(_values(role, value))
        return {k: one(EXPR, v) for k, v in value.items()}
    return value


def _expr_fields(mode: str) -> List[Tuple[str, str]]:
    return [(f, r) for f, r in MODES[mode].items() if r in (EXPR, EQUATION, EXPR_LIST, EQUATION_LIST, SOLUTION)]


# ── R1: key order ─────────────────────────────────────────────────────────────────────────────────────────────
def _reversed_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _reversed_keys(obj[k]) for k in reversed(list(obj))}
    if isinstance(obj, list):
        return [_reversed_keys(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_reversed_keys(v) for v in obj)
    return copy.deepcopy(obj)


def _changed(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> Tuple[int, ...]:
    return tuple(i for i, (b, a) in enumerate(zip(before, after)) if _wire(b) != _wire(a))


def _r1_build(subject: Any):
    steps, _ = _subject(subject)
    after = _reversed_keys(subject)
    return after, None, _changed(steps, _subject(after)[0])


def r1_oracle(before: Any, after: Any) -> Optional[str]:
    try:
        cb, ca = canonical_json_bytes(before), canonical_json_bytes(after)
    except (TypeError, ValueError) as e:
        return f"not JSON: {e}"
    if cb != ca:
        return "canonical_json_bytes differ"
    if not _same(before, after):
        return "a value or its type changed (canonical JSON cannot see it)"
    return None


# ── R2: an equality's two sides swapped ───────────────────────────────────────────────────────────────────────
def _side(v: Any) -> Any:
    """What the oracle compares of one side: its parse tree, or the number itself."""
    if isinstance(v, str):
        return ast.dump(_tree(v))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (type(v).__name__, repr(v))
    raise Decline(f"an equality side that is neither a string nor a number ({type(v).__name__})")


def _r2_params(mode: str, params: Dict[str, Any]):
    a, b = params.get("expr_a"), params.get("expr_b")
    if a is None or b is None:
        raise Decline("an equality side is missing")
    if _side(a) == _side(b):
        raise Decline("the two sides parse alike")
    return {k: copy.deepcopy(b if k == "expr_a" else a if k == "expr_b" else v) for k, v in params.items()}, None


def _r2_build(subject: Any):
    after, _, done = _per_step(subject, _r2_params, only="equality")
    return after, None, done


def _r2_judge(mode: str, pb: Dict[str, Any], pa: Dict[str, Any]) -> Optional[str]:
    if "expr_a" not in pb or "expr_b" not in pb or "expr_a" not in pa or "expr_b" not in pa:
        return "an equality side is missing"
    others = lambda p: {k: v for k, v in p.items() if k not in ("expr_a", "expr_b")}  # noqa: E731
    if not _same(others(pb), others(pa)):
        return "a field other than the two sides changed"
    try:
        if _side(pa["expr_a"]) != _side(pb["expr_b"]) or _side(pa["expr_b"]) != _side(pb["expr_a"]):
            return "the parsed sides are not the two sides exchanged"
    except Decline as d:
        return str(d)
    return None


def r2_oracle(before: Any, after: Any) -> Optional[str]:
    return _step_oracle(before, after, _r2_judge, only="equality")


# ── R3: whitespace between tokens ─────────────────────────────────────────────────────────────────────────────
_SKIP = frozenset({tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.INDENT, tokenize.DEDENT})
_REFUSE = frozenset({tokenize.COMMENT, tokenize.STRING, tokenize.ERRORTOKEN}
                    | {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END",
                                                      "TSTRING_START", "TSTRING_MIDDLE", "TSTRING_END")
                       if hasattr(tokenize, n)})


def _tokens(core: str) -> List[tokenize.TokenInfo]:
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(core).readline) if t.type not in _SKIP]
    except (tokenize.TokenError, SyntaxError, IndentationError) as e:
        raise Decline(f"{core!r} does not tokenize: {e}")
    if any(t.type in _REFUSE for t in toks):
        raise Decline(f"{core!r} holds a comment or a string")
    return toks


def _spaced_piece(piece: str) -> str:
    _tree(piece)
    lead, core, trail = _core(piece)
    toks = _tokens(core)
    out = []
    for j, t in enumerate(toks):
        if j:
            gap = core[toks[j - 1].end[1]:t.start[1]]
            if gap.strip():
                raise Decline(f"{core!r}: something other than whitespace between two tokens")
            out.append(gap + " ")
        out.append(core[t.start[1]:t.end[1]])
    return lead + "".join(out) + trail


def _spaced(role: str, s: str) -> str:
    return _join(role, [_spaced_piece(p) for p in _pieces(role, s)])


def _r3_params(mode: str, params: Dict[str, Any]):
    new = {}
    for k, v in params.items():
        role = MODES[mode].get(k)
        new[k] = _map_field(role, v, _spaced) if role in (EXPR, EQUATION, EXPR_LIST, EQUATION_LIST, SOLUTION) \
            else copy.deepcopy(v)
    why = _size_reason(params, new)
    if why:
        raise Decline(why)
    return new, None


def _r3_build(subject: Any):
    after, _, done = _per_step(subject, _r3_params)
    return after, None, done


def _spaces_inserted(b: str, a: str) -> bool:
    """a is b with spaces inserted, and nothing else."""
    i = 0
    for ch in a:
        if i < len(b) and ch == b[i]:
            i += 1
        elif ch != " ":
            return False
    return i == len(b)


def _r3_piece(b: str, a: str) -> Optional[str]:
    try:
        tb, ta = _tree(b), _tree(a)
        kb = [(t.type, t.string) for t in _tokens(b.strip())]
        ka = [(t.type, t.string) for t in _tokens(a.strip())]
    except Decline as d:
        return str(d)
    if not _spaces_inserted(b, a):
        return f"{a!r} is not {b!r} with spaces inserted"
    if _core(b)[0] != _core(a)[0] or _core(b)[2] != _core(a)[2]:
        return f"{a!r} gained whitespace before its first token or after its last"
    if kb != ka:
        return f"{a!r} does not tokenize as {b!r} does (a space inside a token)"
    if ast.dump(tb) != ast.dump(ta):
        return f"{a!r} does not parse as {b!r} does"
    return None


def _r3_judge(mode: str, pb: Dict[str, Any], pa: Dict[str, Any]) -> Optional[str]:
    if list(pb) != list(pa):
        return "the params' fields changed"
    for k in pb:
        role = MODES[mode].get(k)
        if role not in (EXPR, EQUATION, EXPR_LIST, EQUATION_LIST, SOLUTION):
            if not _same(pb[k], pa[k]):
                return f"{k} changed, and it holds no expression"
            continue
        try:
            vb, va = list(_values(role, pb[k])), list(_values(role, pa[k]))
        except Decline as d:
            return str(d)
        if role == SOLUTION and list(pb[k]) != list(pa[k]):
            return "claimed_solution's keys changed"
        if len(vb) != len(va):
            return f"{k} changed its length"
        for (r, b), (_, a) in zip(vb, va):
            if not (isinstance(b, str) and isinstance(a, str)):
                if not _same(b, a):
                    return f"{k}: a value that is not a string changed"
                continue
            try:
                xb, xa = _pieces(r, b), _pieces(r, a)
            except Decline as d:
                return str(d)
            if len(xb) != len(xa):
                return f"{k}: {a!r} splits differently from {b!r}"
            for p, q in zip(xb, xa):
                why = _r3_piece(p, q)
                if why:
                    return f"{k}: {why}"
    return _size_reason(pb, pa)


def r3_oracle(before: Any, after: Any) -> Optional[str]:
    return _step_oracle(before, after, _r3_judge)


# ── R4: capture-safe symbol renaming ──────────────────────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=None)
def _plain(name: str) -> bool:
    """sympify(name) is the plain Symbol(name), with no locals. Only ever given an identifier (an evaluated
    identifier is a lookup, never a call): _renamable checks the shape first, and new names match NEW_NAME."""
    from sympy import Symbol, sympify
    try:
        v = sympify(name)
    except Exception:  # noqa: BLE001 — a name sympify cannot read is not a plain symbol
        return False
    return type(v) is Symbol and v == Symbol(name)


def _renamable(name: str) -> bool:
    """A name whose meaning in every mapped mode is a plain symbol, whatever it is called."""
    return (isinstance(name, str) and bool(_IDENT.fullmatch(name)) and name.lower() != "mod"
            and name not in _KEPT_NAMES and _plain(name))


def _fresh(name: str, taken) -> bool:
    return bool(NEW_NAME.fullmatch(name)) and name not in taken and _plain(name)


def _names_of(tree: ast.Expression) -> Tuple[List[ast.Name], set]:
    """Every Name in walk order, and the ids of the Name nodes that are called."""
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return [n for n in ast.walk(tree) if isinstance(n, ast.Name)], called


def _r4_tree(piece: str) -> ast.Expression:
    """The parse of one piece R4 may rename, or Decline: nothing in it can name a symbol but a bare name."""
    tree = _tree(piece)
    text = piece.strip()
    for n in ast.walk(tree):                     # strings first: each names what a rename of the names cannot see
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)):
            raise Decline(f"{text!r} holds a string ({n.value!r}), which can name a symbol the rename does not reach")
        if _STRING_NODES and isinstance(n, _STRING_NODES):
            raise Decline(f"{text!r} holds a formatted string, which can name a symbol the rename does not reach")
    for n in ast.walk(tree):
        if not isinstance(n, R4_SHAPE):
            raise Decline(f"{text!r} holds an {type(n).__name__}, which can compute a name; R4 does not map it")
        if isinstance(n, ast.Constant) and not (n.value is None or isinstance(n.value, (int, float, complex))):
            raise Decline(f"{text!r} holds the constant {n.value!r}, which R4 does not map")
        if isinstance(n, ast.keyword) and n.arg is None:
            raise Decline(f"{text!r} unpacks keyword arguments, which R4 does not map")
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name):
                raise Decline(f"{text!r} calls something other than a name, which R4 does not map")
            if n.func.id not in R4_FUNCTIONS:
                raise Decline(f"{text!r} calls {n.func.id!r}, which R4 cannot show takes no name from a string "
                              f"and returns none")
    return tree


def _expression_names(mode: str, params: Dict[str, Any]) -> Tuple[List[str], set, set]:
    """(symbol names in source order, called names, every name) across the mode's expression fields."""
    symbols, called, every = [], set(), set()
    for f, role in _expr_fields(mode):
        if f not in params:
            continue
        for r, v in _values(role, params[f]):
            if not isinstance(v, str):
                continue
            for piece in _pieces(r, v):
                names, calls = _names_of(_r4_tree(piece))
                for n in sorted(names, key=lambda n: n.col_offset):
                    every.add(n.id)
                    if id(n) in calls:
                        called.add(n.id)
                    elif n.id not in symbols:
                        symbols.append(n.id)
    both = sorted(set(symbols) & called)
    if both:
        raise Decline(f"{both[0]!r} is both called and used as a symbol")
    return symbols, called, every


def _param_names(mode: str, params: Dict[str, Any]) -> List[str]:
    """The names the mode's symbol-naming parameters give, in order (the variable as the mode reads it)."""
    out: List[str] = []
    for f, role in MODES[mode].items():
        if role == VARIABLE:
            v = params.get(f, DEFAULT_VARIABLE.get(mode))
            if not isinstance(v, str):
                raise Decline(f"{f} is not a name")
            out.append(v)
        elif role == NAMES and f in params:
            v = params[f]
            if v is None or v == {}:
                continue
            if isinstance(v, dict):
                raise Decline(f"{f} is a non-empty object, which R4 cannot map")
            if not isinstance(v, list) or not all(isinstance(n, str) for n in v):
                raise Decline(f"{f} is not a list of names")
            out.extend(v)
        elif role == SOLUTION and isinstance(params.get(f), dict):
            if not all(isinstance(k, str) for k in params[f]):
                raise Decline(f"{f} has a key that is not a name")
            out.extend(params[f])
    return out


def _renamed(role: str, s: str, m: Dict[str, str]) -> str:
    out = []
    for piece in _pieces(role, s):
        lead, core, trail = _core(piece)
        names, calls = _names_of(_r4_tree(piece))
        spans = sorted((n.col_offset, n.end_col_offset, m[n.id]) for n in names if id(n) not in calls and n.id in m)
        text, at = [], 0
        for start, end, new in spans:
            text.append(core[at:start] + new)
            at = end
        out.append(lead + "".join(text) + core[at:] + trail)
    return _join(role, out)


def _r4_params(mode: str, params: Dict[str, Any]):
    unknown = [k for k in params if k not in MODES[mode]]
    if unknown:
        raise Decline(f"{unknown[0]!r} is not a field R4 maps for mode {mode}")
    symbols, called, every = _expression_names(mode, params)
    pnames = _param_names(mode, params)
    olds = [n for n in symbols if _renamable(n)]
    if not olds:
        raise Decline("no free symbol to rename")
    olds += [n for n in dict.fromkeys(pnames) if n not in olds and n not in called and _renamable(n)]
    taken = every | set(pnames)
    news, k = [], 0
    while len(news) < len(olds):
        cand = f"v{k}"
        if _fresh(cand, taken):
            news.append(cand)
        k += 1
    m = dict(zip(olds, news))
    new: Dict[str, Any] = {}
    for f, v in params.items():
        role = MODES[mode][f]
        if role in (EXPR, EQUATION, EXPR_LIST, EQUATION_LIST):
            new[f] = _map_field(role, v, lambda r, s: _renamed(r, s, m))
        elif role == SOLUTION:
            new[f] = {m.get(key, key): (_renamed(EXPR, val, m) if isinstance(val, str) else copy.deepcopy(val))
                      for key, val in v.items()} if isinstance(v, dict) else copy.deepcopy(v)
        elif role == VARIABLE:
            new[f] = m.get(v, v)
        elif role == NAMES and isinstance(v, list):
            new[f] = [m.get(n, n) for n in v]
        else:
            new[f] = copy.deepcopy(v)
    for f, role in MODES[mode].items():
        if role == VARIABLE and f not in new:
            d = DEFAULT_VARIABLE[mode]
            new[f] = m.get(d, d)              # written in explicitly: the default is never relied on
    why = _size_reason(params, new)
    if why:
        raise Decline(why)
    return new, m


def _r4_build(subject: Any):
    after, maps, done = _per_step(subject, _r4_params)
    return after, maps, done


def _pairs(mode: str, pb: Dict[str, Any], pa: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
    """(before name, after name, called) for every name position, or Decline: the trees must match name for name."""
    out: List[Tuple[str, str, bool]] = []
    for f, role in MODES[mode].items():
        if role in (EXPR, EQUATION, EXPR_LIST, EQUATION_LIST, SOLUTION):
            if (f in pb) != (f in pa):
                raise Decline(f"{f} was added or removed")
            if f not in pb:
                continue
            if role == SOLUTION and isinstance(pb[f], dict):
                if not isinstance(pa[f], dict) or len(pb[f]) != len(pa[f]):
                    raise Decline("claimed_solution changed its length")
                out += [(k, ka, False) for k, ka in zip(pb[f], pa[f])]
            vb, va = list(_values(role, pb[f])), list(_values(role, pa[f]))
            if len(vb) != len(va):
                raise Decline(f"{f} changed its length")
            for (r, b), (_, a) in zip(vb, va):
                if not (isinstance(b, str) and isinstance(a, str)):
                    if not _same(b, a):
                        raise Decline(f"{f}: a value that is not a string changed")
                    continue
                xb, xa = _pieces(r, b), _pieces(r, a)
                if len(xb) != len(xa):
                    raise Decline(f"{f}: {a!r} splits differently from {b!r}")
                for p, q in zip(xb, xa):
                    tb, ta = _r4_tree(p), _r4_tree(q)
                    nb, cb = _names_of(tb)
                    na_, ca = _names_of(ta)
                    if _blank(tb) != _blank(ta) or len(nb) != len(na_):
                        raise Decline(f"{f}: {q.strip()!r} is not {p.strip()!r} with its names changed")
                    for x, y in zip(nb, na_):
                        if (id(x) in cb) != (id(y) in ca):
                            raise Decline(f"{f}: a call and a symbol traded places")
                        out.append((x.id, y.id, id(x) in cb))
        elif role == VARIABLE:
            d = DEFAULT_VARIABLE.get(mode)
            if f not in pa:
                raise Decline(f"the mode reads {f} (default {d!r}), and the restatement does not write it in")
            out.append((pb.get(f, d), pa[f], False))
        elif role == NAMES:
            b, a = pb.get(f), pa.get(f)
            if (f in pb) != (f in pa):
                raise Decline(f"{f} was added or removed")
            if isinstance(b, list) and isinstance(a, list) and len(b) == len(a):
                out += [(x, y, False) for x, y in zip(b, a)]
            elif not (b is None or b == {}) or not _same(b, a):
                raise Decline(f"{f} is not a list of names mapped name for name")
    return out


def _blank(tree: ast.Expression) -> str:
    """The tree's dump with every name blanked: the structure the rename must keep."""
    t = copy.deepcopy(tree)
    for n in ast.walk(t):
        if isinstance(n, ast.Name):
            n.id = "_"
    return ast.dump(t)


def _r4_judge(mode: str, pb: Dict[str, Any], pa: Dict[str, Any]) -> Optional[str]:
    unknown = [k for k in list(pb) + list(pa) if k not in MODES[mode]]
    if unknown:
        return f"{unknown[0]!r} is not a field R4 maps for mode {mode}"
    for f, role in MODES[mode].items():
        if role == OTHER and ((f in pb) != (f in pa) or not _same(pb.get(f), pa.get(f))):
            return f"{f} changed, and it names no symbol"
    try:
        pairs = _pairs(mode, pb, pa)
        _, _, every = _expression_names(mode, pb)
        taken = every | set(_param_names(mode, pb))
    except Decline as d:
        return str(d)
    fwd: Dict[str, str] = {}
    back: Dict[str, str] = {}
    for old, new, called in pairs:
        if not isinstance(old, str) or not isinstance(new, str):
            return "a symbol-naming parameter that is not a name"
        if fwd.setdefault(old, new) != new:
            return f"{old!r} is renamed to both {fwd[old]!r} and {new!r}"
        if back.setdefault(new, old) != old:
            return f"{back[new]!r} and {old!r} are both renamed to {new!r}"
        if old != new and called:
            return f"the called name {old!r} was renamed"
    for old, new in fwd.items():
        if old == new:
            continue
        if not _renamable(old):
            return f"{old!r} is not a plain symbol in every mapped mode, so renaming it changes what it means"
        if not NEW_NAME.fullmatch(new):
            return f"the new name {new!r} is not drawn from {NEW_NAME.pattern}"
        if not _plain(new):
            return f"sympify({new!r}) is not the plain Symbol({new!r})"
        if new in taken:
            return f"the new name {new!r} is not fresh: the claim already names it"
    return _size_reason(pb, pa)


def r4_oracle(before: Any, after: Any) -> Optional[str]:
    return _step_oracle(before, after, _r4_judge)


# ── R5: step ids ──────────────────────────────────────────────────────────────────────────────────────────────
def _uses(step: Dict[str, Any], i: int) -> List[Any]:
    uses = step.get("uses")
    if not uses:
        return []
    if not isinstance(uses, list):
        raise Decline(f"step {i}'s uses is not a list")
    return uses


def _id_refs(steps: List[Dict[str, Any]], doc: Optional[Dict[str, Any]]) -> set:
    """Every string a step id could be matched against: the ids, every uses entry, every bind source, every
    {reference} in a document's text."""
    refs = set(_effective_ids(steps))
    for i, s in enumerate(steps):
        refs |= {str(u) for u in _uses(s, i)}
        for _, ref in _bind_items(s):
            if not isinstance(ref, str):
                raise Decline(f"step {i} has a bind reference that is not a string")
            refs.add(ref.partition(".")[0])
    text = (doc or {}).get("text")
    if isinstance(text, str):
        refs |= set(_BRACE.findall(text))
    return refs


def _rewrite_ref(ref: str, m: Dict[str, str]) -> str:
    src, dot, key = ref.partition(".")
    return m.get(src, src) + dot + key


def _rewrite_text(text: str, m: Dict[str, str]) -> str:
    return _BRACE.sub(lambda g: "{" + m.get(g.group(1), g.group(1)) + "}", text)


def _r5_build(subject: Any):
    steps, doc = _subject(subject)
    refs = _id_refs(steps, doc)
    olds = list(dict.fromkeys(_effective_ids(steps)))
    news, k = [], 0
    while len(news) < len(olds):
        if f"r{k}" not in refs:
            news.append(f"r{k}")
        k += 1
    m = dict(zip(olds, news))
    out = []
    for i, (s, sid) in enumerate(zip(steps, _effective_ids(steps))):
        new: Dict[str, Any] = {}
        for key, v in s.items():
            if key == "id":
                new[key] = m[sid]
            elif key == "uses" and v:
                new[key] = [m.get(str(u), copy.deepcopy(u)) for u in _uses(s, i)]
            elif key == "bind" and _bind_items(s):
                new[key] = {p: _rewrite_ref(ref, m) for p, ref in _bind_items(s)}
            else:
                new[key] = copy.deepcopy(v)
        if "id" not in new:
            new["id"] = m[sid]                # a default id made explicit
        out.append(new)
    fields = {}
    if doc is not None and isinstance(doc.get("text"), str):
        fields["text"] = _rewrite_text(doc["text"], m)
    return _rebuild(subject, out, **fields), m, _changed(steps, out)


def r5_oracle(before: Any, after: Any) -> Optional[str]:
    try:
        sb, db = _subject(before)
        sa, da = _subject(after)
        refs = _id_refs(sb, db)
        _id_refs(sa, da)
    except Decline as d:
        return str(d)
    if (db is None) != (da is None) or len(sb) != len(sa):
        return "the subject's form or its number of steps changed"
    eb, ea = _effective_ids(sb), _effective_ids(sa)
    fwd: Dict[str, str] = {}
    back: Dict[str, str] = {}
    for i, (b, a) in enumerate(zip(eb, ea)):
        if fwd.setdefault(b, a) != a:
            return f"the carriers of {b!r} were renamed apart (a collision undone)"
        if back.setdefault(a, b) != b:
            return f"{back[a]!r} and {b!r} were both renamed to {a!r} (a collision made)"
        if not sa[i].get("id") or not isinstance(sa[i]["id"], str):
            return f"step {i} has no explicit string id after the rename"
    for old, new in fwd.items():
        if "." in new:
            return f"the new id {new!r} holds '.', where a bind reference splits"
        if old != new and new in refs:
            return f"the new id {new!r} is not fresh: the derivation already refers to it"
    for i, (b, a) in enumerate(zip(sb, sa)):
        if b.get("uses"):
            if [fwd.get(str(u), str(u)) for u in _uses(b, i)] != [str(u) for u in _uses(a, i)]:
                return f"step {i}'s uses are not its old uses under the id map"
        elif ("uses" in b) != ("uses" in a) or not _same(b.get("uses"), a.get("uses")):
            return f"step {i} gained a uses"
        bb, ba = _bind_items(b), _bind_items(a)
        if bb:
            if [p for p, _ in bb] != [p for p, _ in ba] or any(
                    _rewrite_ref(r, fwd) != q for (_, r), (_, q) in zip(bb, ba)):
                return f"step {i}'s bind is not its old bind under the id map"
        elif ("bind" in b) != ("bind" in a) or not _same(b.get("bind"), a.get("bind")):
            return f"step {i} gained a bind"
        rest = lambda s: {k: v for k, v in s.items() if k not in ("id", "uses", "bind")}  # noqa: E731
        if not _same(rest(b), rest(a)):
            return f"step {i} changed in more than its id, uses and bind"
    if db is not None:
        others = lambda d: {k: v for k, v in d.items() if k not in ("steps", "text")}  # noqa: E731
        if not _same(others(db), others(da)):
            return "a document field other than its steps and text changed"
        tb, ta = db.get("text"), da.get("text")
        if isinstance(tb, str):
            if ta != _rewrite_text(tb, fwd):
                return "the document's {step_id} text is not its old text under the id map"
        elif not _same(tb, ta):
            return "the document's text changed"
    return None


# ── the registry ──────────────────────────────────────────────────────────────────────────────────────────────
REGISTRY: Tuple[Restatement, ...] = (
    Restatement("R1", "key order", "every domain", _r1_build, r1_oracle),
    Restatement("R2", "equality swap", "mathematics, mode equality", _r2_build, r2_oracle),
    Restatement("R3", "whitespace between tokens", "mathematics, the modes in MODES", _r3_build, r3_oracle),
    Restatement("R4", "symbol rename", "mathematics, the modes in MODES", _r4_build, r4_oracle),
    Restatement("R5", "step-id rename", "derivation-tier rows: a closure audit (verifiers never see ids)",
                _r5_build, r5_oracle),
)
BY_KEY: Mapping[str, Restatement] = MappingProxyType({r.key: r for r in REGISTRY})


def restate(key: str, subject: Any) -> Outcome:
    """Restatement `key` of `subject`: applied (its oracle passed the result) or declined with the reason."""
    r = BY_KEY[key]
    try:
        after, mapping, done = r.build(subject)
    except Decline as d:
        return Outcome(key, reason=str(d))
    if _wire(after) == _wire(subject):
        return Outcome(key, reason="it changes no byte")
    why = r.oracle(subject, after)
    if why:
        return Outcome(key, reason=f"its oracle refuses it: {why}")
    return Outcome(key, after=after, mapping=mapping, restated=done)


__all__ = ["REGISTRY", "BY_KEY", "MODES", "DEFAULT_VARIABLE", "Outcome", "Restatement", "Decline", "restate",
           "r1_oracle", "r2_oracle", "r3_oracle", "r4_oracle", "r5_oracle"]
