"""Run the edge translator with a small ONBOARD model — no API key, no cloud.

The claims below are deliberately twisted (word numbers, loose wording) so the deterministic
extractors miss them and the model has to translate — you'll see `reached_by` = "model". The verdict
is still the engine's exact recompute, so a mis-translation can never make a false claim HOLD.

Setup (pick one), then `python integrations/examples/try_onboard.py`:

    # Ollama — easiest, no compiler:
    pip install ollama
    ollama pull qwen2.5:0.5b            # ~400 MB, runs on CPU

    # or llama.cpp with a local GGUF file:
    pip install llama-cpp-python
    # download e.g. Qwen2.5-0.5B-Instruct-Q4_K_M.gguf from Hugging Face, then set MODEL below.

The engine itself must be importable: `pip install concordance` (or run from the repo with
PYTHONPATH=src).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))   # the integrations package

from concordance_integrations.models import ollama_model  # noqa: E402  (or llamacpp_model)
from concordance_integrations.translate import verify_text  # noqa: E402

# Change this to your backend / model:
MODEL = ollama_model("qwen2.5:0.5b")
# MODEL = llamacpp_model("/path/to/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf")

CLAIMS = [
    "borrowing twelve thousand at six percent for a year comes to about 1032.80 a month",       # HOLDS
    "a quarter-million loan against a four-hundred-thousand property sits at a 62.5% LTV",       # HOLDS
    "net operating income of 24,000 with debt service of 22,755 gives a coverage ratio of 1.055",  # HOLDS
    "borrowing twelve thousand at six percent for a year comes to about 5,000 a month",          # BROKEN
    # a geometric WORD problem — the keyword resolver routes "ladder/wall" to architecture; the
    # planner (candidates>1) adds geometry as a candidate action and attends to the one that reaches:
    "a ladder ten feet long with its base six feet from the wall reaches eight feet up",         # HOLDS (6-8-10)
    "a ladder ten feet long with its base six feet from the wall reaches nine feet up",          # BROKEN
]

if __name__ == "__main__":
    for c in CLAIMS:
        # candidates=4 = plan over several candidate domains per round; the verdict is the engine's.
        r = verify_text(c, model=MODEL, max_rounds=3, candidates=4)
        print(f"[{str(r.get('reached_by')):9}] {str(r.get('verdict')):11} {c[:62]}")
        if r.get("proposed_packet"):
            print("            the model asked the engine to check:", r["proposed_packet"])
