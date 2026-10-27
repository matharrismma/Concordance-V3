"""The edge translator — a model in front of the engine, so natural phrasing reaches the verifier.

This is the forward pass of the figure: the model *proposes* what to check; the engine *recomputes*
the answer. The model never produces the verdict, so it cannot make a false claim HOLD — the
zero-false-positive guarantee is untouched. A mis-translation costs only recall (the wrong thing is
checked, or nothing is), never trust, and the result carries `proposed_packet` so a reader sees
exactly what was checked.

A cascade, cheapest first:
  1. the deterministic extractors recognise the claim (the common-core head) — free, exact, no model;
  2. only if they find nothing, the model fills the resolved domain's packet schema, and that packet
     is verified deterministically;
  3. if no model is given, or no verifiable claim can be reached, an honest null.

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
                config: Any = None, max_rounds: int = 1) -> Dict[str, Any]:
    """Verify a natural-language claim, reaching the verifier by extractor or model (the cascade).
    Returns the engine's result with `reached_by` ("extractor" | "model" | "none"); the model path
    also carries `proposed_packet` — exactly what the model asked the engine to check.

    `max_rounds` > 1 runs the PID correction loop: when the model's packet does not reach a verifier
    (INCOMPLETE / nothing filled), the engine's error is fed back and the model tries again, up to
    `max_rounds` times. The loop acts only on that rectified error — not reaching the verifier — and
    STOPS the instant a verdict is reached. It never loops to turn a BROKEN into a HOLDS: the error it
    corrects is "did we reach the check", never "did the claim pass", so a small model can be nudged to
    a complete packet while the 0-false-positive guarantee is untouched."""
    res = engine.verify(claim=text, seal=seal, config=config)
    if res.get("claims_found", 0) > 0:
        res["reached_by"] = "extractor"
        return res
    if model is None:
        res["reached_by"] = "none"
        return res
    feedback: Optional[str] = None
    acc: Dict[str, Any] = {}        # the Markov chain's state — fields built up across rounds
    acc_dom: Optional[str] = None
    acc_ak: Optional[str] = None
    for _ in range(max(1, int(max_rounds))):
        steps, ctx = translate(text, model, config=config, feedback=feedback)
        if steps:
            dom = steps[0]["domain"]
            ak = next(iter(steps[0]["spec"]))
            if ak != acc_ak or dom != acc_dom:       # domain changed -> start a fresh accumulation
                acc, acc_ak, acc_dom = {}, ak, dom
            acc.update(steps[0]["spec"][ak])          # later rounds add and override earlier fields
            merged = [{"id": "t", "domain": acc_dom, "spec": {acc_ak: dict(acc)}}]
            out = engine.verify(steps=merged, seal=seal, config=config)
            if out.get("verdict") in ("HOLDS", "BROKEN"):   # reached the band — done, never flip it
                out["reached_by"] = "model"
                out["proposed_packet"] = merged[0]["spec"]
                return out
            feedback = _feedback(ctx, "not reached yet (verdict " + str(out.get("verdict"))
                                 + "); fields so far: " + ", ".join(acc.keys()))
        else:
            feedback = _feedback(ctx, ctx.get("note", "no packet was produced"))
    res["reached_by"] = "none"
    return res


def translate(text: str, model: Model, *, config: Any = None,
              feedback: Optional[str] = None) -> tuple:
    """Resolve the domain, have the model fill that domain's packet schema, and return
    (steps | None, ctx). `steps` is a single verify step [{id, domain, spec}]; `ctx` carries the
    domain and field names for the correction loop's feedback. `feedback` from a prior round is
    appended to the prompt."""
    from concordance.config import EngineConfig
    from concordance.mcp import server as _server
    cfg = config or EngineConfig()
    fv = _server._call_tool("find_verifier", {"query": text}, cfg)
    domain = fv.get("domain") or fv.get("decision")
    sch = (fv.get("schemas") or {}).get(domain) or {}
    ak = sch.get("artifact_key")
    fields = _fields(sch, ak)
    if not (domain and ak and fields):
        return None, {"note": "no verifiable domain resolved for this text"}
    ctx = {"domain": domain, "fields": list(fields.keys())}
    parsed = _parse_json(model(_prompt(text, domain, ak, ctx["fields"], feedback)))
    if not isinstance(parsed, dict):
        return None, {**ctx, "note": "the model did not return a JSON object"}
    if ak in parsed and isinstance(parsed[ak], dict):   # model wrapped it in the artifact key
        parsed = parsed[ak]
    clean = {k: v for k, v in parsed.items() if k in fields}
    if not clean:
        return None, {**ctx, "note": "none of the filled fields are in the schema"}
    return [{"id": "t", "domain": domain, "spec": {ak: clean}}], ctx


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
