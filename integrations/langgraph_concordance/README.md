# langgraph-concordance

Concordance as a LangGraph node, a verdict router, and a LangChain tool. Talks to a running engine
(`CONCORDANCE_URL` or `url=`) or runs the engine in-process when `concordance` is installed.

```bash
pip install -e integrations/concordance_client -e integrations/langgraph_concordance
```

```python
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph_concordance import make_verify_node, route_on_verdict, concordance_verify

class S(TypedDict, total=False):
    output: str; packets: Any; concordance: dict

g = StateGraph(S)
g.add_node("model", my_model_node)                       # writes state["output"] (and optionally "packets")
g.add_node("verify", make_verify_node(input_key="output", result_key="concordance"))
g.add_edge(START, "model"); g.add_edge("model", "verify")
g.add_conditional_edges("verify", route_on_verdict, {"holds": END, "broken": "model", "unchecked": END})
print(concordance_verify.invoke({"claim": "15% of 200 is 30"}))   # the same check as an agent tool
```

The node reads `state[input_key]`: JSON with `steps` / `document` / `{mode, params}` is verified as such,
anything else is a plain-language claim; `state[packets_key]` overrides it when the harness knows the packets.
It writes `{score, passed, reason, verdict, read, checked, cite_url, seal_hash, budget, trace}` under
`result_key`. `route_on_verdict` returns `"holds"`, `"broken"` or `"unchecked"`. `on_unchecked="pass"` scores
an unchecked claim 1.0 (still `checked=False`).

Score semantics are shared with every adapter and are not a truth score — see
[integrations/README.md](../README.md#score-semantics-the-same-in-every-adapter).
