"""Ready-made model wrappers for the edge translator — BYOM made turnkey.

Each returns a plain `str -> str` callable (the `translate.Model` protocol), so:

    from concordance_integrations.translate import verify_text
    from concordance_integrations.models import anthropic_model, openai_model

    verify_text(claim, model=anthropic_model("claude-sonnet-4-5"))         # ANTHROPIC_API_KEY
    verify_text(claim, model=openai_model("gpt-4.1-mini"))                 # OPENAI_API_KEY
    verify_text(claim, model=openai_model("meta-llama/llama-3.3-70b-instruct",
                base_url="https://openrouter.ai/api/v1"))                 # any OpenAI-compatible host

The SDK is imported lazily, inside the call, so importing this module costs nothing and the
translator core stays dependency-free. You pass the model id yourself — this library never pins a
model name that would go stale. Install the SDK you use: `pip install anthropic` or `pip install
openai`.
"""
from __future__ import annotations

from typing import Callable, Optional

# Keep the translator deterministic: temperature 0, a short cap (it emits a small JSON packet).
_SYSTEM = ("You extract numbers from a sentence into a fixed JSON schema for a deterministic "
           "verifier. You never answer or judge the claim. Output only the JSON object.")


def anthropic_model(model: str, *, api_key: Optional[str] = None, max_tokens: int = 512,
                    temperature: float = 0.0) -> Callable[[str], str]:
    """An Anthropic (Claude) model as a str->str callable. Uses ANTHROPIC_API_KEY when api_key is None."""
    def call(prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        msg = client.messages.create(model=model, max_tokens=max_tokens, temperature=temperature,
                                     system=_SYSTEM, messages=[{"role": "user", "content": prompt}])
        return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text")
    return call


def openai_model(model: str, *, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 max_tokens: int = 512, temperature: float = 0.0) -> Callable[[str], str]:
    """An OpenAI or any OpenAI-compatible model (OpenRouter, Together, Groq, vLLM, …) as a str->str
    callable. Pass `base_url` for a compatible host; uses OPENAI_API_KEY when api_key is None."""
    def call(prompt: str) -> str:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""
    return call
