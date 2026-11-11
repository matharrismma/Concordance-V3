"""THE PROBE and THE WALK of run 2026-11-11-exact-integers: where a verifier reads an integer by dropping its
fraction, or takes a bool for one, through int(), round() with one argument, math.floor, math.ceil or math.trunc.

A SITE is one call in a file under src/concordance/verifiers/, written as the file, the enclosing function and the
call's source text with its occurrence number in that function, never a line:

    combinatorics.py:verify_permutations:int(n)#1

The enclosing function is the nearest def (a method as Class.method, a nested def as outer.inner, code outside any
def as <module>); a lambda or a comprehension is part of the function that holds it. The text is the call's source,
its runs of white space read as one space, and the occurrence counts the calls of that function with the same text,
in source order. Both measures key their sites this way (site_index), so each can check the other.

THE PROBE (Python 3.12 or later: it watches calls with sys.monitoring). For each check in data/check_goldens.jsonl
(a name carried by more than one row reads "<name> #2" for its second row, and so on) whose true spec reads HOLDS
with no fault, it varies each integer leaf of that spec (an int, never a bool, at any depth), one at a time, to
v+0.25 and v-0.25, and a leaf of 0 or 1 also to the bool of the same truth, and reads each variant as the benchmark
reads a check: derivation.verify_derivation([{"id": "c", "domain": ..., "spec": ...}]). It watches the CALL events
of int, round, math.floor, math.ceil and math.trunc made from a file under src/concordance/verifiers/ (a round only
where its call holds one argument and no keyword, read from the file's syntax tree). Such a call is LOSSY when it
receives a bool or a finite float with a fraction. A FINDING is a lossy call in a variant that either receives the
injected value itself ("direct": the injected bool, or a float equal to the injected one) or sits at a site with no
lossy call in the clean read of the same check ("derived"). It is keyed by check, leaf path ("COMB_VERIFY/perm_n"),
variant ("+0.25", "-0.25", "bool") and site; how and the variant's verdict are recorded beside it, and a finding
counts whatever that verdict. A leaf no check reads makes no call and so no finding. A finding at a site named in
tests/integer_fields.json is not counted: it is reported under "excluded", and a named site that receives an
injected value itself is a problem, since such a site reads through THE RULE.

It measures in its own child process: CONCORDANCE_MEMO=0; CONCORDANCE_VERIFY_TIMEOUT_S raised to --timeout-s (600 by
default; derivation.py:68 reads 8 when unset), so no read is shed; PYTHONHASHSEED=0; every other CONCORDANCE_*
variable of the caller dropped, so caller code never runs and a test's setting never reaches it; the CAS, ledger,
memo bucket and data dir in a temporary copy of data/'s reference files (tools/halt_telemetry.py's isolated(),
imported, not copied); every verifier module imported and the heavy libraries warmed before the first read; and an
audit hook that counts any write into this repository's data/. It FAILS, never skips, when a read times out or the
pool is busy (derivation's own warning, or a step it shed), when a check's true spec does not read HOLDS clean, when
a lossy call cannot be placed at a site, when anything writes into data/, or when the engine was imported from
another tree; it stops at the first such failure, so a worker a timeout left running can never write calls into
the next case, and the child then exits at once, never waiting on such a worker. With that it is deterministic: two
runs give the same findings. It reads the goldens and the source and writes nothing but its --json report.

It exits 0 when it measured and its findings equal tests/integer_probe_known.json (for the checks it measured) with
no named field receiving an injected value; 1 when a finding is not in the known list, a known entry was not found,
or a named field receives an injected value; 2 when it measured nothing, was given bad arguments, or runs below
Python 3.12; 3 when the probe itself failed, as above.

THE WALK (any Python). It parses each file under src/concordance/verifiers/ and follows each function's assignments
from its parameters. A value is MARKED when it is a parameter (a lambda's included), a name a nested def reads from
the def that holds it, or is computed from a marked value by attribute, subscript, arithmetic or any other
expression, or by a call with a marked argument or a marked callee (spec.get("n")). A name is marked when a marked
value is assigned to it, including through unpacking (a, b = x, y pairs each name with its own value), augmented
assignment, a walrus, a with's target, a match's capture, a for loop's target and a comprehension or generator's
target; a container is marked when a marked value is stored into it (out["n"] = ...) or handed to one of its
filling methods (MUTATORS: vals.append(...), d.update(...)). A value is UNMARKED when it comes from THE RULE's
readers (_exact_integer and _claimed_integer, by name, called bare or as an attribute), len(), a comparison, a
literal or a lambda; a call to any other function, mathematics' list reader _exact_integers among them, is a call
like any other. The marking is flow-insensitive: a name marked anywhere in its function is marked everywhere in it.
A FINDING is an int(), one-argument round(), math.floor, math.ceil or math.trunc call (by the math module's name or
alias, or a name imported from it) whose first argument is marked, unless its site is named in
tests/integer_fields.json or it is the conversion inside THE RULE's two shared readers themselves: the top-level
functions _exact_integer and _claimed_integer of src/concordance/verifiers/_integer.py (SHARED_MODULE), which
convert only a value they have already found whole. That exemption is by those names in that module only: the same
readers anywhere else (mathematics.py holds them at the base), and any other function of that module, are walked
like any other.

    PYTHONPATH=src python tools/integer_probe.py [--check NAME ...] [--goldens PATH] [--known PATH|none]
                                                 [--timeout-s S] [--json PATH]
    python tools/integer_probe.py --walk [--json PATH]
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
VERIFIERS = ROOT / "src" / "concordance" / "verifiers"
DATA = ROOT / "data"
GOLDENS = DATA / "check_goldens.jsonl"
FIELDS = ROOT / "tests" / "integer_fields.json"
KNOWN = ROOT / "tests" / "integer_probe_known.json"
WALK_KNOWN = ROOT / "tests" / "integer_walk_known.json"
HALT_TELEMETRY = ROOT / "tools" / "halt_telemetry.py"

SHARED_MODULE = "_integer.py"                          # THE RULE's one shared module, under VERIFIERS
READERS = ("_exact_integer", "_claimed_integer")       # THE RULE's two readers
UNMARKING_CALLS = frozenset(READERS)                   # by name, called bare or as an attribute
MATH_CALLS = ("floor", "ceil", "trunc")
MUTATORS = frozenset({"append", "extend", "insert", "add", "update", "setdefault", "appendleft", "extendleft"})
VARIANTS = ("+0.25", "-0.25", "bool")
TIMEOUT_S = 600.0
CHILD_TIMEOUT_S = 3 * 3600
MIN_PYTHON = (3, 12)
NEEDS = "sys.monitoring needs Python 3.12"
_SHED = ("verify timed out", "verify pool saturated")                  # derivation's own warnings
_SHED_DETAIL = ("verification timed out", "verifier busy")             # derivation's own step details


# ── sites ─────────────────────────────────────────────────────────────────────────────────────────────────────────
class Scope:
    """A def, a class body or the module: its path, the nodes evaluated in it, and its own parameters."""

    def __init__(self, path: str, kind: str, node: ast.AST, parent: Optional["Scope"]):
        self.path, self.kind, self.node, self.parent = path, kind, node, parent
        self.nodes: List[ast.AST] = []
        self.params: Set[str] = set()


class Site(NamedTuple):
    file: str
    function: str
    text: str
    n: int
    node: ast.Call
    scope: Scope

    @property
    def key(self) -> str:
        return site_key(self.file, self.function, self.text, self.n)


def site_key(file: str, function: str, text: str, n: int) -> str:
    return f"{file}:{function}:{text}#{n}"


def _params(args: ast.arguments) -> Set[str]:
    out = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    out |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
    return out


def scopes(tree: ast.Module) -> List[Scope]:
    """Every scope of a module, each listed before the scopes it holds. A def's decorators, defaults and annotations
    are evaluated in the scope that holds it; a lambda and a comprehension belong to the scope that holds them."""
    out: List[Scope] = []

    def inner_path(scope: Scope, name: str) -> str:
        return name if scope.kind == "module" else f"{scope.path}.{name}"

    def visit_arguments(args: ast.arguments, scope: Scope) -> None:
        for d in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            visit(d, scope)
        for a in args.posonlyargs + args.args + args.kwonlyargs + [x for x in (args.vararg, args.kwarg) if x]:
            if a.annotation is not None:
                visit(a.annotation, scope)

    def visit(node: ast.AST, scope: Scope) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.nodes.append(node)
            for d in node.decorator_list:
                visit(d, scope)
            visit_arguments(node.args, scope)
            if node.returns is not None:
                visit(node.returns, scope)
            inner = Scope(inner_path(scope, node.name), "def", node, scope)
            inner.params = _params(node.args)
            out.append(inner)
            for s in node.body:
                visit(s, inner)
            return
        if isinstance(node, ast.ClassDef):
            scope.nodes.append(node)
            for d in node.decorator_list + node.bases + [k.value for k in node.keywords]:
                visit(d, scope)
            inner = Scope(inner_path(scope, node.name), "class", node, scope)
            out.append(inner)
            for s in node.body:
                visit(s, inner)
            return
        if isinstance(node, ast.Lambda):
            scope.nodes.append(node)
            visit_arguments(node.args, scope)
            scope.params |= _params(node.args)
            visit(node.body, scope)
            return
        scope.nodes.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    module = Scope("<module>", "module", tree, None)
    out.append(module)
    for s in tree.body:
        visit(s, module)
    return out


class _Segments:
    """ast.get_source_segment over one source, its lines split once (that function splits them on every call)."""

    def __init__(self, source: str):
        self.lines = [line.encode("utf-8") for line in io.StringIO(source, newline="").readlines()]

    def __call__(self, node: ast.AST) -> Optional[str]:
        try:
            ln, eln, col, ecol = node.lineno - 1, node.end_lineno - 1, node.col_offset, node.end_col_offset
        except AttributeError:
            return None
        if None in (ln, eln, col, ecol) or not (0 <= ln <= eln < len(self.lines)):
            return None
        if ln == eln:
            return self.lines[ln][col:ecol].decode("utf-8")
        return b"".join([self.lines[ln][col:]] + self.lines[ln + 1:eln] + [self.lines[eln][:ecol]]).decode("utf-8")


def _text(segment: Callable[[ast.AST], Optional[str]], node: ast.AST) -> str:
    """The call's source text, its runs of white space read as one space."""
    seg = segment(node)
    return " ".join((seg if seg is not None else ast.unparse(node)).split())


class Index(NamedTuple):
    sites: List[Site]
    scopes: List[Scope]
    tree: ast.Module
    source: str


def site_index(path: Path, rel: Optional[str] = None) -> Index:
    """Every call of a file as a site, numbered in source order within its scope, with the file's scopes (each
    listed before the scopes it holds), tree and source."""
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    rel = rel or Path(path).name
    sites: List[Site] = []
    every = scopes(tree)
    segment = _Segments(source)
    for scope in every:
        calls = sorted((n for n in scope.nodes if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
        seen: Counter = Counter()
        for call in calls:
            text = _text(segment, call)
            seen[text] += 1
            sites.append(Site(rel, scope.path, text, seen[text], call, scope))
    return Index(sites, every, tree, source)


def verifier_files(vdir: Path = VERIFIERS) -> List[Tuple[Path, str]]:
    """(path, its site name) for each .py file under vdir, in sorted order; the name is the path from vdir."""
    vdir = Path(vdir)
    return [(p, p.relative_to(vdir).as_posix()) for p in sorted(vdir.rglob("*.py")) if "__pycache__" not in p.parts]


def is_one_argument_round(call: ast.Call) -> bool:
    return (len(call.args) == 1 and not call.keywords and not isinstance(call.args[0], ast.Starred))


def math_aliases(tree: ast.Module) -> Tuple[Set[str], Dict[str, str]]:
    """The names bound to the math module anywhere in a file, and each name bound to math.floor, ceil or trunc."""
    modules: Set[str] = set()
    names: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "math":
                    modules.add(a.asname or "math")
        elif isinstance(node, ast.ImportFrom) and node.module == "math" and not node.level:
            for a in node.names:
                if a.name in MATH_CALLS:
                    names[a.asname or a.name] = a.name
    return modules, names


def lossy_kind(call: ast.Call, modules: Set[str], names: Dict[str, str]) -> Optional[str]:
    """"int", "round", "floor", "ceil" or "trunc" when the call is one of the five, else None."""
    f = call.func
    if isinstance(f, ast.Name):
        if f.id == "int":
            return "int"
        if f.id == "round":
            return "round" if is_one_argument_round(call) else None
        return names.get(f.id)
    if (isinstance(f, ast.Attribute) and f.attr in MATH_CALLS and isinstance(f.value, ast.Name)
            and f.value.id in modules):
        return f.attr
    return None


# ── THE WALK ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _callee(func: ast.expr) -> Optional[str]:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def marked(e: Optional[ast.AST], M: Set[str]) -> bool:
    """True when the value of expression e is computed from a marked value."""
    if e is None or isinstance(e, (ast.Constant, ast.Compare, ast.Lambda)):
        return False
    if isinstance(e, ast.Name):
        return e.id in M
    if isinstance(e, ast.Call):
        name = _callee(e.func)
        if name in UNMARKING_CALLS or (name == "len" and isinstance(e.func, ast.Name)):
            return False
        return (marked(e.func, M) or any(marked(a, M) for a in e.args)
                or any(marked(k.value, M) for k in e.keywords))
    if isinstance(e, ast.IfExp):
        return marked(e.body, M) or marked(e.orelse, M)
    if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return marked(e.elt, M)
    if isinstance(e, ast.DictComp):
        return marked(e.key, M) or marked(e.value, M)
    return any(marked(c, M) for c in ast.iter_child_nodes(e) if isinstance(c, ast.expr))


def _target_names(t: ast.AST) -> List[str]:
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        return [n for e in t.elts for n in _target_names(e)]
    if isinstance(t, ast.Starred):
        return _target_names(t.value)
    if isinstance(t, (ast.Attribute, ast.Subscript)):        # a store into a container marks the container
        base = t.value
        while isinstance(base, (ast.Attribute, ast.Subscript)):
            base = base.value
        return [base.id] if isinstance(base, ast.Name) else []
    return []


def _pattern_names(pattern: ast.AST) -> List[str]:
    """The names a match case captures: case {"n": n}, case [first, *rest], case {**rest}."""
    names = []
    for x in ast.walk(pattern):
        if isinstance(x, (ast.MatchAs, ast.MatchStar)) and x.name:
            names.append(x.name)
        elif isinstance(x, ast.MatchMapping) and x.rest:
            names.append(x.rest)
    return names


def _pairs(target: ast.AST, value: ast.AST) -> Iterator[Tuple[List[str], ast.AST]]:
    """a, b = x, y pairs a with x and b with y; any other unpacking gives each name the whole value."""
    if (isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
            and not any(isinstance(e, ast.Starred) for e in target.elts + value.elts)):
        for t, v in zip(target.elts, value.elts):
            yield from _pairs(t, v)
    else:
        yield _target_names(target), value


def _flows(node: ast.AST) -> Iterator[Tuple[List[str], ast.AST]]:
    """(the names a node binds or fills, the value they take) for each flow of a value into a name."""
    if isinstance(node, ast.Assign):
        for t in node.targets:
            yield from _pairs(t, node.value)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
        yield _target_names(node.target), node.value
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        yield _target_names(node.target), node.iter
    elif isinstance(node, ast.NamedExpr):
        yield _target_names(node.target), node.value
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        yield _target_names(node.optional_vars), node.context_expr
    elif isinstance(node, ast.Match):
        for case in node.cases:
            yield _pattern_names(case.pattern), node.subject
    elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
          and node.value.func.attr in MUTATORS):
        call = node.value                                   # vals.append(x): the container holds what it was handed
        handed = ast.Tuple(elts=list(call.args) + [k.value for k in call.keywords], ctx=ast.Load())
        yield _target_names(call.func), handed


def _marks(scope: Scope, inherited: Set[str]) -> Set[str]:
    M = set(scope.params) | inherited
    flows = [f for n in scope.nodes for f in _flows(n)]
    changed = True
    while changed:
        changed = False
        for names, value in flows:
            new = [n for n in names if n not in M]
            if new and marked(value, M):
                M.update(new)
                changed = True
    return M


def exempt_reader(site: Site) -> bool:
    """The conversion inside THE RULE's two shared readers: those two top-level functions of SHARED_MODULE only."""
    return site.file == SHARED_MODULE and site.function in READERS


def walk_file(path: Path, rel: Optional[str] = None) -> List[Tuple[Site, str]]:
    """(site, call kind) for each of the five calls in a file whose first argument is marked, before any exemption."""
    index = site_index(path, rel)
    modules, names = math_aliases(index.tree)
    marks: Dict[int, Set[str]] = {}
    for scope in index.scopes:                      # parents first, so a nested def inherits its holder's marks
        holder = scope.parent
        while holder is not None and holder.kind != "def":
            holder = holder.parent
        marks[id(scope)] = _marks(scope, marks[id(holder)] if holder is not None else set())
    out = []
    for site in index.sites:
        kind = lossy_kind(site.node, modules, names)
        if kind and site.node.args and marked(site.node.args[0], marks[id(site.scope)]):
            out.append((site, kind))
    return out


def walk(vdir: Path = VERIFIERS, fields: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """THE WALK over vdir: {"findings": {site key: call kind}, "excluded": {...}, "exempt": {...}}; a site named in
    fields (default: tests/integer_fields.json) is excluded, and THE RULE's own conversion is exempt."""
    named = set(fields if fields is not None else field_sites())
    found: Dict[str, str] = {}
    excluded: Dict[str, str] = {}
    exempt: Dict[str, str] = {}
    for path, rel in verifier_files(vdir):
        for site, kind in walk_file(path, rel):
            (exempt if exempt_reader(site) else excluded if site.key in named else found)[site.key] = kind
    return {"findings": dict(sorted(found.items())), "excluded": dict(sorted(excluded.items())),
            "exempt": dict(sorted(exempt.items()))}


# ── tests/integer_fields.json ─────────────────────────────────────────────────────────────────────────────────────
def load_fields(path: Path = FIELDS) -> List[Dict[str, Any]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(doc.get("fields", []))


def field_sites(path: Path = FIELDS) -> List[str]:
    return [str(f.get("site")) for f in load_fields(path)]


def fields_problems(fields: Sequence[Dict[str, Any]], vdir: Path = VERIFIERS, root: Path = ROOT) -> List[str]:
    """What is wrong with the named fields: each names a site that exists among the calls of vdir, says why, and
    names a test (tests/<file>.py::<function>) that exists; no site is named twice."""
    if not fields:
        return []
    keys = {s.key for p, rel in verifier_files(vdir) for s in site_index(p, rel).sites}
    problems: List[str] = []
    seen: Set[str] = set()
    for f in fields:
        site = f.get("site") if isinstance(f, dict) else None
        if not isinstance(site, str) or site not in keys:
            problems.append(f"names no call in the verifiers: {f!r}")
            continue
        if site in seen:
            problems.append(f"named twice: {site}")
        seen.add(site)
        if not (isinstance(f.get("why"), str) and f["why"].strip()):
            problems.append(f"says no why: {site}")
        test = f.get("test")
        file, _, name = str(test or "").partition("::")
        tpath = Path(root) / file
        if not (file.startswith("tests/") and name and tpath.is_file()
                and f"def {name.split('[')[0]}(" in tpath.read_text(encoding="utf-8")):
            problems.append(f"names no test that exists: {site} -> {test!r}")
    return problems


# ── THE PROBE: the finding rule ───────────────────────────────────────────────────────────────────────────────────
class ProbeFailure(Exception):
    """The probe could not measure: a read shed, a true spec not reading HOLDS, a call it could not place."""


class Read(NamedTuple):
    verdict: str
    events: List[Tuple[str, str, Any]]     # (site key, "bool" or "frac", the argument) for each lossy call
    shed: List[str]                        # derivation's own timeout or busy messages during the read


def int_leaves(obj: Any, path: Tuple = ()) -> Iterator[Tuple[Tuple, int]]:
    """(path, value) for each int leaf, never a bool, at any depth of dicts and lists."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, int):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from int_leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from int_leaves(v, path + (i,))


def variants(v: int) -> List[Tuple[str, Any]]:
    """v+0.25 and v-0.25 (none past a float's range), and for 0 or 1 the bool of the same truth."""
    try:
        out: List[Tuple[str, Any]] = [("+0.25", v + 0.25), ("-0.25", v - 0.25)]
    except OverflowError:
        out = []
    if v in (0, 1):
        out.append(("bool", bool(v)))
    return out


def with_leaf(obj: Any, path: Tuple, value: Any) -> Any:
    copy = json.loads(json.dumps(obj))
    cur = copy
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    return copy


def leaf_name(path: Tuple) -> str:
    return "/".join(str(k) for k in path)


def check_rows(goldens: Path = GOLDENS) -> List[Tuple[str, str, Any]]:
    """(check, domain, true spec) for each row; a name carried by more than one row reads "<name> #2" for its second."""
    rows, seen = [], Counter()
    for line in Path(goldens).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        seen[r["check"]] += 1
        name = r["check"] if seen[r["check"]] == 1 else f"{r['check']} #{seen[r['check']]}"
        rows.append((name, r["domain"], r.get("true")))
    return rows


def _is_direct(kind: str, arg: Any, variant: str, value: Any) -> bool:
    if variant == "bool":
        return kind == "bool" and arg is value
    return kind == "frac" and not isinstance(arg, bool) and arg == value


def probe(rows: Sequence[Tuple[str, str, Any]], read: Callable[[str, Any], Read],
          named: Iterable[str] = ()) -> Dict[str, Any]:
    """The finding rule over rows, with read(domain, spec) doing each read. Raises ProbeFailure at the first read
    that was shed, and at the first check whose true spec does not read HOLDS clean."""
    named = set(named)
    findings: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    runs = 0
    t0 = time.perf_counter()

    def once(check: str, label: str, domain: str, spec: Any) -> Read:
        nonlocal runs
        r = read(domain, spec)
        runs += 1
        if r.shed:
            raise ProbeFailure(f"{check} {label}: a read was shed ({r.shed[0]}); raise --timeout-s")
        return r

    for check, domain, true in rows:
        if true is None:
            raise ProbeFailure(f"{check}: no true spec")
        clean = once(check, "clean", domain, true)
        if clean.verdict != "HOLDS":
            raise ProbeFailure(f"{check}: the true spec reads {clean.verdict} clean, not HOLDS")
        clean_sites = {site for site, _, _ in clean.events}
        for path, v in int_leaves(true):
            for variant, value in variants(v):
                r = once(check, f"{leaf_name(path)} {variant}", domain, with_leaf(true, path, value))
                how: Dict[str, str] = {}
                for site, kind, arg in r.events:
                    if _is_direct(kind, arg, variant, value):
                        how[site] = "direct"
                    elif site not in clean_sites:
                        how.setdefault(site, "derived")
                for site in sorted(how):
                    f = {"check": check, "leaf": leaf_name(path), "variant": variant, "site": site,
                         "how": how[site], "verdict": r.verdict}
                    (excluded if site in named else findings).append(f)
    order = lambda f: (f["site"], f["check"], f["leaf"], VARIANTS.index(f["variant"]))  # noqa: E731
    findings.sort(key=order)
    excluded.sort(key=order)
    return {"checks": len(rows), "runs": runs, "secs": round(time.perf_counter() - t0, 1),
            "findings": findings, "excluded": excluded, "counts": counts(findings)}


def finding_key(f: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (f["check"], f["leaf"], f["variant"], f["site"])


def counts(findings: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    sites = {f["site"] for f in findings}
    return {"findings": len(findings), "leaves": len({(f["check"], f["leaf"]) for f in findings}),
            "sites": len(sites), "files": len({s.split(":", 1)[0] for s in sites}),
            "checks": len({f["check"] for f in findings}),
            "reading_HOLDS": sum(1 for f in findings if f["verdict"] == "HOLDS"),
            "by_variant": dict(sorted(Counter(f["variant"] for f in findings).items())),
            "by_how": dict(sorted(Counter(f["how"] for f in findings).items()))}


def compare(findings: Sequence[Dict[str, Any]], known: Sequence[Dict[str, Any]],
            checks: Optional[Iterable[str]] = None) -> Tuple[List[Tuple], List[Tuple]]:
    """(new, stale): findings not in the known list, and known entries not found, over the checks measured."""
    scope = set(checks) if checks is not None else None
    have = {finding_key(f) for f in findings}
    want = {finding_key(f) for f in known if scope is None or f["check"] in scope}
    return sorted(have - want), sorted(want - have)


def load_known(path: Path = KNOWN) -> List[Dict[str, Any]]:
    return list(json.loads(Path(path).read_text(encoding="utf-8"))["findings"])


def load_walk_known(path: Path = WALK_KNOWN) -> List[str]:
    return list(json.loads(Path(path).read_text(encoding="utf-8"))["sites"])


def tracked_json(rel: str, root: Path = ROOT, rev: str = "HEAD") -> Optional[Any]:
    """A tracked JSON file as rev holds it, or None when rev holds no such file; LookupError when root is not a git
    checkout or rev names nothing there. Each known list may only shrink, so a step's list is held against the one
    its base holds: in a gate's worktree HEAD is the step's base, with the step's paths laid over."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}

    def git(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *argv], capture_output=True, env=env)

    try:
        if git("rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}").returncode != 0:
            raise LookupError(f"{root} holds no git revision {rev}")
    except FileNotFoundError as exc:
        raise LookupError("git is not installed") from exc
    shown = git("show", f"{rev}:{rel}")
    if shown.returncode != 0:
        return None
    return json.loads(shown.stdout.decode("utf-8"))


def fields_direct(excluded: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The findings at a site named in tests/integer_fields.json that received the injected value itself: none may
    be, since such a site reads through THE RULE."""
    return [f for f in excluded if f["how"] == "direct"]


# ── THE PROBE: the watch (sys.monitoring, Python 3.12+) ──────────────────────────────────────────────────────────
class Monitor:
    """Lossy calls of the five from files under vdir, as (site key, kind, argument), through sys.monitoring CALL
    events. A call from any other file disables its location for this tool; one that cannot be placed at a site is
    a problem, never a guess."""

    def __init__(self, vdir: Path = VERIFIERS):
        self.vdir = os.path.normcase(os.path.abspath(str(vdir))) + os.sep
        self.root = Path(vdir)
        self.events: List[Tuple[str, str, Any]] = []
        self.problems: List[str] = []
        self.tool: Optional[int] = None
        self._files: Dict[str, Optional[str]] = {}
        self._ends: Dict[str, Dict[Tuple[int, int], Site]] = {}
        self._positions: Dict[Any, list] = {}
        self._targets = {id(int): "int", id(round): "round", id(math.floor): "floor", id(math.ceil): "ceil",
                         id(math.trunc): "trunc"}

    def _rel(self, filename: str) -> Optional[str]:
        p = os.path.normcase(os.path.abspath(filename))
        if not p.startswith(self.vdir) or not p.endswith(".py"):
            return None
        return Path(os.path.relpath(filename, str(self.root))).as_posix()

    def _site(self, rel: str, filename: str, code, offset: int) -> Optional[Site]:
        ends = self._ends.get(rel)
        if ends is None:
            ends = {}
            for s in site_index(Path(filename), rel).sites:
                at = (s.node.end_lineno, s.node.end_col_offset)
                if at in ends:
                    self.problems.append(f"two calls end at {rel} {at}")
                ends[at] = s
            self._ends[rel] = ends
        pos = self._positions.get(code)
        if pos is None:
            pos = self._positions[code] = list(code.co_positions())
        p = pos[offset // 2] if 0 <= offset // 2 < len(pos) else None
        site = ends.get((p[1], p[3])) if p else None
        if site is None or (p[0] is not None and p[0] < site.node.lineno):
            self.problems.append(f"a call at {rel} offset {offset} {p} is at no site")
            return None
        return site

    def _on_call(self, code, offset, fn, arg0):
        try:
            rel = self._files.get(code.co_filename, "")
            if rel == "":
                rel = self._files[code.co_filename] = self._rel(code.co_filename)
            if rel is None:
                return sys.monitoring.DISABLE
            name = self._targets.get(id(fn))
            if name is None:
                return None
            if isinstance(arg0, bool):
                kind = "bool"
            elif isinstance(arg0, float) and math.isfinite(arg0) and not float(arg0).is_integer():
                kind = "frac"
            else:
                return None
            site = self._site(rel, code.co_filename, code, offset)
            if site is None or (name == "round" and not is_one_argument_round(site.node)):
                return None
            self.events.append((site.key, kind, arg0))
        except Exception as exc:  # noqa: BLE001 — a callback must never raise into the code it watches
            self.problems.append(f"the watch raised {type(exc).__name__}: {exc}")
        return None

    def __enter__(self) -> "Monitor":
        mon = sys.monitoring
        for tid in (4, 5, 3, 2, 0, 1):
            if mon.get_tool(tid) is None:
                self.tool = tid
                break
        else:
            raise ProbeFailure("no free sys.monitoring tool id")
        mon.use_tool_id(self.tool, "integer-probe")
        mon.register_callback(self.tool, mon.events.CALL, self._on_call)
        mon.restart_events()
        mon.set_events(self.tool, mon.events.CALL)
        return self

    def __exit__(self, *exc) -> None:
        mon = sys.monitoring
        mon.set_events(self.tool, 0)
        mon.register_callback(self.tool, mon.events.CALL, None)
        mon.free_tool_id(self.tool)
        mon.restart_events()


# ── THE PROBE: the child that measures ────────────────────────────────────────────────────────────────────────────
def _load_halt_telemetry():
    spec = importlib.util.spec_from_file_location("_integer_probe_halt_telemetry", HALT_TELEMETRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITES = ("open", "os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.truncate", "shutil.rmtree",
           "shutil.copyfile", "shutil.copytree", "shutil.move")


def _data_write_hook(seen: List[str]) -> Callable:
    top = os.path.normcase(os.path.abspath(str(DATA)))

    def inside(p) -> bool:
        if not isinstance(p, (str, bytes, os.PathLike)):
            return False
        q = os.path.normcase(os.path.abspath(os.fsdecode(p)))
        return q == top or q.startswith(top + os.sep)

    def hook(event: str, args) -> None:
        if event not in _WRITES:
            return
        a = tuple(args) + (None,) * 3
        if event == "open":
            mode, flags = a[1], a[2]
            writes = (any(c in mode for c in "wax+") if isinstance(mode, str)
                      else bool(isinstance(flags, int) and flags & _WRITE_FLAGS))
            paths = (a[0],) if writes else ()
        elif event in ("os.rename", "shutil.copyfile", "shutil.copytree", "shutil.move"):
            paths = (a[0], a[1]) if event == "os.rename" else (a[1],)
        else:
            paths = (a[0],)
        for p in paths:
            if inside(p):
                seen.append(f"{event} {os.fsdecode(p)}")

    return hook


def _child(args: argparse.Namespace) -> int:
    out = Path(args.child_out)
    report: Dict[str, Any] = {"failure": None}
    try:
        if sys.version_info < MIN_PYTHON:
            report["failure"] = NEEDS
            return 2
        src = str(ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        named = field_sites(Path(args.fields))
        rows = check_rows(Path(args.goldens))
        if args.check:
            wanted = set(args.check)
            missing = sorted(wanted - {r[0] for r in rows})
            if missing:
                report["failure"] = f"no such check: {missing}"
                return 2
            rows = [r for r in rows if r[0] in wanted]
        HT = _load_halt_telemetry()
        writes: List[str] = []
        with HT.isolated():
            import concordance
            from concordance import derivation as D
            here = os.path.normcase(os.path.abspath(os.path.dirname(concordance.__file__)))
            if here != os.path.normcase(os.path.abspath(str(ROOT / "src" / "concordance"))):
                raise ProbeFailure(f"the engine was imported from {here}, not this tree")
            if D._VERIFY_TIMEOUT_S != float(args.timeout_s):
                raise ProbeFailure(f"the verify timeout reads {D._VERIFY_TIMEOUT_S}, not {args.timeout_s}")
            D.warm()
            unimported = []
            for path, rel in verifier_files(VERIFIERS):
                if rel != "__init__.py":
                    name = "concordance.verifiers." + rel[:-3].replace("/", ".")
                    try:
                        importlib.import_module(name)
                    except Exception as exc:  # noqa: BLE001 — an optional dependency may be absent
                        unimported.append(f"{name}: {type(exc).__name__}")
            report["unimported"] = unimported
            import logging
            shed: List[str] = []

            class _Shed(logging.Handler):
                def emit(self, record):
                    if str(record.msg).startswith(_SHED):
                        shed.append(record.getMessage())

            D._log.addHandler(_Shed(logging.WARNING))
            if D._log.getEffectiveLevel() > logging.WARNING:
                D._log.setLevel(logging.WARNING)
            sys.addaudithook(_data_write_hook(writes))

            with Monitor(VERIFIERS) as mon:
                def read(domain: str, spec: Any) -> Read:
                    del mon.events[:], shed[:]
                    try:
                        r = D.verify_derivation([{"id": "c", "domain": domain, "spec": spec}])
                        verdict = str(r.get("verdict"))
                        for t in r.get("trail") or []:
                            if t.get("status") == "ERROR" and str(t.get("detail", "")).startswith(_SHED_DETAIL):
                                shed.append(str(t.get("detail")))
                    except Exception as exc:  # noqa: BLE001 — recorded as the variant's reading
                        verdict = f"raised {type(exc).__name__}"
                    if mon.problems:
                        raise ProbeFailure(mon.problems[0])
                    if writes:
                        raise ProbeFailure(f"a read wrote into data/: {writes[0]}")
                    return Read(verdict, list(mon.events), list(shed))

                report.update(probe(rows, read, named))
        report["python"] = sys.version.split()[0]
        report["timeout_s"] = float(args.timeout_s)
        return 0
    except ProbeFailure as exc:
        report["failure"] = str(exc)
        return 3
    finally:
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


def child_env(timeout_s: float) -> Dict[str, str]:
    """The child's environment: the caller's, less every CONCORDANCE_* variable and the harness's own, with the
    memo off, the verify timeout raised, hashing fixed and this tree's src first on the path."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CONCORDANCE_", "HARNESS_", "VACUITY_"))}
    env.update(CONCORDANCE_MEMO="0", CONCORDANCE_VERIFY_TIMEOUT_S=repr(float(timeout_s)), PYTHONHASHSEED="0")
    rest = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src")] + rest)
    return env


def measure(check: Sequence[str] = (), goldens: Path = GOLDENS, fields: Path = FIELDS,
            timeout_s: float = TIMEOUT_S) -> Tuple[int, Dict[str, Any], str]:
    """Run the probe in its own child process: (its exit code, its report, the tail of its output)."""
    with tempfile.TemporaryDirectory(prefix="integer-probe-") as tmp:
        out = Path(tmp) / "report.json"
        cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "--child-out", str(out),
               "--goldens", str(goldens), "--fields", str(fields), "--timeout-s", repr(float(timeout_s))]
        for c in check:
            cmd += ["--check", c]
        t0 = time.perf_counter()
        try:
            p = subprocess.run(cmd, cwd=str(ROOT), env=child_env(timeout_s), capture_output=True, text=True,
                               timeout=CHILD_TIMEOUT_S)
            rc, tail = p.returncode, (p.stdout[-2000:] + p.stderr[-4000:])
        except subprocess.TimeoutExpired:
            return 3, {"failure": f"the child ran past {CHILD_TIMEOUT_S} s"}, ""
        if not out.exists():
            return 3, {"failure": f"the child exited {rc} with no report"}, tail
        report = json.loads(out.read_text(encoding="utf-8"))
        report["wall_s"] = round(time.perf_counter() - t0, 1)
        if rc != 0 and not report.get("failure"):
            report["failure"] = f"the child exited {rc}"
        return rc, report, tail


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="append", default=[], help="measure only this check (repeatable)")
    ap.add_argument("--goldens", default=str(GOLDENS))
    ap.add_argument("--fields", default=str(FIELDS))
    ap.add_argument("--known", default=str(KNOWN), help="the known list, or none")
    ap.add_argument("--timeout-s", type=float, default=TIMEOUT_S)
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--walk", action="store_true", help="run THE WALK instead")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--child-out", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.child:
        rc = _child(args)
        if rc == 3:                       # the probe failed: a worker a timeout left running is never waited on
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(rc)
        return rc
    if args.walk:
        rep = walk(fields=field_sites(Path(args.fields)))
        rep["known"] = load_walk_known() if WALK_KNOWN.exists() else None
        if rep["known"] is not None:
            rep["new"] = sorted(set(rep["findings"]) - set(rep["known"]))
            rep["stale"] = sorted(set(rep["known"]) - set(rep["findings"]))
        print(f"THE WALK: {len(rep['findings'])} findings in {len({k.split(':', 1)[0] for k in rep['findings']})} "
              f"files; {len(rep.get('new') or [])} new, {len(rep.get('stale') or [])} stale")
        if args.json:
            Path(args.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        return 1 if rep.get("new") or rep.get("stale") else 0
    if sys.version_info < MIN_PYTHON:
        print(f"integer_probe: {NEEDS}; this is {sys.version.split()[0]}", file=sys.stderr)
        return 2
    rc, rep, tail = measure(args.check, Path(args.goldens), Path(args.fields), args.timeout_s)
    if rc == 0 and not rep.get("failure"):
        if not rep.get("runs"):
            rep["failure"], rc = "measured nothing", 2
        else:
            if args.known != "none":
                new, stale = compare(rep["findings"], load_known(Path(args.known)),
                                     args.check or None)
                rep["new"], rep["stale"] = [list(k) for k in new], [list(k) for k in stale]
            rep["fields_direct"] = fields_direct(rep["excluded"])
            rep["fields_problems"] = fields_problems(load_fields(Path(args.fields)))
            if rep.get("new") or rep.get("stale") or rep["fields_direct"] or rep["fields_problems"]:
                rc = 1
    elif rc == 0:
        rc = 3
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    if rep.get("failure"):
        print(f"THE PROBE FAILED: {rep['failure']}", file=sys.stderr)
        if tail.strip():
            print(tail, file=sys.stderr)
    else:
        c = rep["counts"]
        print(f"THE PROBE: {rep['checks']} checks, {rep['runs']} reads, {rep['secs']} s; {c['findings']} findings "
              f"on {c['leaves']} leaves at {c['sites']} sites in {c['files']} files ({c['reading_HOLDS']} reading "
              f"HOLDS); {len(rep.get('new') or [])} new, {len(rep.get('stale') or [])} stale")
    return rc


if __name__ == "__main__":
    sys.exit(main())
