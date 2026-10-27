"""The edge translator — a model in front of the engine, so natural phrasing reaches the verifier.

This is the forward pass of the figure: the model *proposes* what to check; the engine *recomputes*
the answer. The model never produces the verdict, so it cannot make a false claim HOLD — the
zero-false-positive guarantee is untouched. A mis-translation costs only recall (the wrong thing is
checked, or nothing is), never trust, and the result carries `proposed_packet` so a reader sees
exactly what was checked.

A cascade, cheapest first:
  1. the deterministic extractors recognise the claim (the common-core head) — free, exact, no model;
  2. only if they find nothing, the model fills a resolved domain's packet schema, and that packet is
     verified deterministically;
  3. if no model is given, or no verifiable claim can be reached, an honest null.

Step 2 is a receding-horizon planner (MPC) with `candidates` > 1. Each round:
  measure the state (what is accumulated) -> the resolver hands back several candidate domains (the
  possible actions) -> the model fills each (the dynamics: an action -> a proposed packet) -> the
  engine predicts each trajectory (does this packet REACH a verifier?) -> a recall-only cost ranks
  them -> commit only the FIRST action (the chosen fields) -> measure again. Selection is attention:
  the claim is the Query, each candidate domain's signature a Key, each proposed packet a Value, and
  several heads attend for different uses (one head: did it reach a verifier; another: how many stated
  fields it filled). Two rules keep the covenant: it is HARD attention (argmin -> one exact Value,
  never a softmax blend of packets, which would fabricate a value); and the verdict is CAUSALLY MASKED
  out of selection -- no head may attend to HOLDS vs BROKEN, so the planner optimises recall only and
  can never steer a claim toward passing. The engine's exact recompute remains the only verdict.

`candidates` = 1 (the default) is the degenerate plan: the single top domain, exactly as before.

Bring your own model: any callable `str -> str` (a prompt in, a completion out). The core stays
model-free; this layer sits in front of it.

    from concordance_integrations.translate import verify_text
    def my_model(prompt):  # wrap OpenAI / Anthropic / a local model in three lines
        return client.responses.create(model="...", input=prompt).output_text
    verify_text("borrowing 12k at 6% over a year runs about 1032.80 a month", model=my_model)
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from . import engine

Model = Callable[[str], str]   # BYOM: a prompt in, a completion out


def verify_text(text: str, *, model: Optional[Model] = None, seal: bool = False,
                config: Any = None, max_rounds: int = 1, candidates: int = 1) -> Dict[str, Any]:
    """Verify a natural-language claim, reaching the verifier by extractor or model (the cascade).
    Returns the engine's result with `reached_by` ("extractor" | "model" | "none"); the model path
    also carries `proposed_packet` — exactly what the model asked the engine to check.

    `candidates` > 1 turns the model step into a receding-horizon planner (MPC): each round resolves
    several candidate domains (the actions), the model fills each (the dynamics), the engine predicts
    each trajectory (does the packet reach a verifier?), a recall-only cost ranks them by attention
    across heads, and only the first action — the chosen fields — is committed before measuring again.
    Selection is HARD (one exact packet, never a blend) and the verdict is masked out of it, so the
    planner optimises recall only. `candidates` = 1 is the degenerate plan: the single top domain.

    `max_rounds` > 1 runs the correction loop across rounds: when no candidate reaches a verifier, the
    engine's error is fed back and the model tries again, up to `max_rounds` times, accumulating fields
    (a Markov chain). The loop STOPS the instant a verdict is reached and never flips BROKEN -> HOLDS:
    the error it corrects is "did we reach the check", never "did the claim pass", so a small model can
    be nudged to a complete packet while the 0-false-positive guarantee is untouched."""
    res = engine.verify(claim=text, seal=seal, config=config)
    if res.get("claims_found", 0) > 0:
        res["reached_by"] = "extractor"
        return res
    if model is None:
        res["reached_by"] = "none"
        return res
    k = max(1, int(candidates))
    feedback: Optional[str] = None
    acc: Dict[str, Any] = {}        # the Markov chain's state — fields built up across rounds
    acc_dom: Optional[str] = None
    acc_ak: Optional[str] = None
    for _ in range(max(1, int(max_rounds))):
        cands, ctx = _candidates(text, model, config=config, feedback=feedback, k=k)
        if not cands:
            feedback = _feedback(ctx, ctx.get("note", "no packet was produced"))
            continue
        # Simulate each action's trajectory (reachability only, seal=False) and ATTEND: argmin over the
        # recall cost. The verdict (HOLDS vs BROKEN) is never a term in the cost — the causal mask.
        best = min(cands, key=lambda c: _plan_cost(engine.verify(steps=[c["step"]], seal=False, config=config), c)) \
            if len(cands) > 1 else cands[0]
        if best["ak"] != acc_ak or best["domain"] != acc_dom:   # the chosen action changed -> fresh accumulation
            acc, acc_ak, acc_dom = {}, best["ak"], best["domain"]
        acc.update(best["spec"])                                # implement the FIRST action: commit its fields
        merged = [{"id": "t", "domain": acc_dom, "spec": {acc_ak: dict(acc)}}]
        out = engine.verify(steps=merged, seal=seal, config=config)   # measure again: the engine's recompute IS the verdict
        if out.get("verdict") in ("HOLDS", "BROKEN"):   # reached the band — done, never flip it
            out["reached_by"] = "model"
            out["proposed_packet"] = merged[0]["spec"]
            return out
        feedback = _feedback(best["ctx"], "not reached yet (verdict " + str(out.get("verdict"))
                             + "); fields so far: " + ", ".join(acc.keys()))
    res["reached_by"] = "none"
    return res


def _plan_cost(pred: Dict[str, Any], cand: Dict[str, Any]) -> tuple:
    """The attention read-out, as a cost to minimise — several heads, each for a different use, NONE of
    them the verdict. Head 1: did the packet reach a verifier (HOLDS and BROKEN collapse to the SAME
    value — that collapse IS the causal mask). Head 2: how many stated fields it filled (more is
    better). Lower wins; ties are stable, so a true claim and its false twin plan identically."""
    reached = 0 if pred.get("verdict") in ("HOLDS", "BROKEN") else 1
    filled = -int(cand.get("filled", 0))
    return (reached, filled)


# Cue -> extra candidate domain. The keyword resolver routes on surface words, so a geometric word
# problem ("a ladder 10 ft long, base 6 ft out, reaches 8 ft up") can resolve to architecture, not
# geometry. Adding geometry as a candidate ACTION whenever a geometric cue is present can only improve
# recall: if the model cannot fill a reaching geometry packet the recall cost discards it, and if it
# can but the claim is false the engine still returns BROKEN. The engine's recompute stays the verdict.
_CUE_DOMAINS = {
    "geometry": re.compile(
        r"\b(triangle|hypotenuse|right[- ]angled?|right angle|\blegs?\b|perimeter|area of|radius|"
        r"circumference|diameter|rectangle|\bsquare\b|polygon|pentagon|hexagon|heptagon|octagon|"
        r"sphere|cylinder|\bcube\b|isosceles|equilateral|pythag|ladder)\b", re.I),
}


def _resolve_domains(text: str, config: Any, k: int) -> tuple:
    """The candidate actions: the resolver's top-k domains, each as (domain, artifact_key, field_names),
    augmented with any cue-triggered domain (e.g. geometry) not already present. Returns (list, cfg)."""
    from concordance.config import EngineConfig
    from concordance.mcp import server as _server
    from concordance import schema as _schema
    cfg = config or EngineConfig()
    fv = _server._call_tool("find_verifier", {"query": text}, cfg)
    schemas = dict(fv.get("schemas") or {})
    top = fv.get("domain") or fv.get("decision")
    order = ([top] if top else []) + [d for d in schemas if d != top]
    order = order[:max(1, k)]
    for dom, cue in _CUE_DOMAINS.items():                 # integrate cue-signalled domains (geometry)
        if dom not in order and cue.search(text or ""):
            order.append(dom)
            schemas.setdefault(dom, _schema.schema_for(dom))
    out = []
    for dom in order:
        sch = schemas.get(dom) or _schema.schema_for(dom)
        ak = sch.get("artifact_key")
        fields = _fields(sch, ak)
        if dom and ak and fields:
            out.append((dom, ak, list(fields.keys())))
    return out, cfg


def _candidates(text: str, model: Model, *, config: Any = None, feedback: Optional[str] = None,
                k: int = 1) -> tuple:
    """Fill each candidate domain's packet schema with the model (the dynamics: action -> packet).
    Returns (candidate list, ctx). Each candidate: {domain, ak, spec, filled, step, ctx}. A candidate
    the model cannot fill is dropped — it is simply not an available action this round."""
    doms, _cfg = _resolve_domains(text, config, k)
    if not doms:
        return [], {"note": "no verifiable domain resolved for this text"}
    cands: List[Dict[str, Any]] = []
    last_ctx: Dict[str, Any] = {}
    for (dom, ak, fields) in doms:
        last_ctx = {"domain": dom, "fields": fields}
        parsed = _parse_json(model(_prompt(text, dom, ak, fields, feedback)))
        if not isinstance(parsed, dict):
            continue
        if ak in parsed and isinstance(parsed[ak], dict):    # model wrapped it in the artifact key
            parsed = parsed[ak]
        clean = {kk: vv for kk, vv in parsed.items() if kk in fields}
        if not clean:
            continue
        cands.append({"domain": dom, "ak": ak, "spec": clean, "filled": len(clean),
                      "step": {"id": "t", "domain": dom, "spec": {ak: dict(clean)}},
                      "ctx": {"domain": dom, "fields": fields}})
    return cands, last_ctx


def translate(text: str, model: Model, *, config: Any = None,
              feedback: Optional[str] = None) -> tuple:
    """Back-compatible single-action resolve: the top candidate domain filled by the model, as
    (steps | None, ctx). Equivalent to the planner with candidates=1."""
    cands, ctx = _candidates(text, model, config=config, feedback=feedback, k=1)
    if not cands:
        return None, ctx
    c = cands[0]
    return [c["step"]], c["ctx"]


def _feedback(ctx: Dict[str, Any], why: str) -> str:
    names = ", ".join((ctx.get("fields") or [])[:40])
    base = ("Previous attempt failed: " + why + ". ")
    if ctx.get("domain"):
        base += ("Domain " + str(ctx["domain"]) + " needs a complete set for one check. Fill only the "
                 "fields the sentence states, using these exact names (numbers only, rates as decimals): "
                 + names + ". ")
    return base + "Output ONLY the JSON object."


def _fields(sch: Dict[str, Any], ak: Optional[str]) -> Dict[str, Any]:
    if not ak:
        return {}
    return (sch.get("packet", {}).get("properties", {}).get(ak, {}) or {}).get("properties", {}) or {}


def _prompt(text: str, domain: str, ak: str, names: List[str],
            feedback: Optional[str] = None) -> str:
    head = (feedback + "\n\n") if feedback else ""   # the rectified error from the prior round
    return (
        head +
        "You convert a sentence into a structured claim for a deterministic verifier. Do not answer "
        "the claim or judge whether it is true — only extract the numbers it states.\n"
        f"Domain: {domain}. Return a JSON object filling ONLY the fields the sentence actually states, "
        "using these exact field names; omit every field not stated. Values are plain numbers (no "
        "units, no currency symbols); rates and percentages as decimals (6% -> 0.06).\n"
        f"Available fields: {', '.join(names[:40])}\n"
        f'Sentence: "{text}"\n'
        "Output ONLY the JSON object, nothing else:"
    )


def _parse_json(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, str):
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None
