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


# ── Onboard (local, no API key) ──────────────────────────────────────────────────────────────
# The translator's job is tiny — fill a JSON schema with the numbers in a sentence — and the engine
# is the backstop (a mis-fill costs recall, never trust), so a very small local model is the right
# fit. A 0.5–1.5B instruct model runs fine on CPU: Qwen2.5-0.5B/1.5B-Instruct, Llama-3.2-1B-Instruct,
# or SmolLM2-1.7B-Instruct. Two ways to run it with no key:

def ollama_model(model: str, *, host: Optional[str] = None, temperature: float = 0.0,
                 options: Optional[dict] = None) -> Callable[[str], str]:
    """A local model served by Ollama — no API key. `pip install ollama`, then e.g.
    `ollama pull qwen2.5:0.5b`. `model` is the Ollama tag (e.g. 'qwen2.5:0.5b', 'llama3.2:1b')."""
    def call(prompt: str) -> str:
        import ollama
        client = ollama.Client(host=host) if host else ollama
        resp = client.generate(model=model, prompt=prompt, system=_SYSTEM,
                                options={"temperature": temperature, **(options or {})})
        return resp.get("response", "") if isinstance(resp, dict) else getattr(resp, "response", "")
    return call


def llamacpp_model(model_path: str, *, n_ctx: int = 2048, temperature: float = 0.0,
                   max_tokens: int = 512, **kwargs) -> Callable[[str], str]:
    """A local GGUF model via llama.cpp — no API key, no server. `pip install llama-cpp-python`,
    then download a small GGUF (e.g. Qwen2.5-0.5B-Instruct-Q4_K_M.gguf from Hugging Face) and pass its
    path. The model loads once, lazily, and is reused across calls."""
    holder: dict = {"llm": None}

    def call(prompt: str) -> str:
        from llama_cpp import Llama
        if holder["llm"] is None:
            holder["llm"] = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False, **kwargs)
        out = holder["llm"].create_chat_completion(
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            temperature=temperature, max_tokens=max_tokens)
        return out["choices"][0]["message"]["content"] or ""
    return call
