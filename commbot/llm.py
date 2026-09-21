"""
Thin wrapper around a Hugging Face hosted LLM.

The whole system works WITHOUT an LLM (keyword rules take over). That's
deliberate: during a disaster the internet link to an inference API is
exactly the kind of thing that fails. The LLM is an upgrade, not a crutch.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, model: str, token: str, timeout: int = 30):
        from huggingface_hub import InferenceClient  # imported lazily on purpose

        self.model = model
        self.client = InferenceClient(model=model, token=token, timeout=timeout)

    def complete(self, system: str, user: str, max_tokens: int = 600) -> str | None:
        try:
            out = self.client.chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                # Low temperature: we want the same facts every time, not creativity.
                temperature=0.1,
            )
            return out.choices[0].message.content
        except Exception as exc:  # network, rate limit, model loading...
            log.warning("LLM call failed (%s), falling back to rules", exc)
            return None


def get_llm(settings) -> LLMClient | None:
    if not settings.llm_enabled or not settings.hf_token:
        return None
    try:
        return LLMClient(settings.hf_model, settings.hf_token)
    except ImportError:
        log.warning("huggingface_hub not installed; running without an LLM")
        return None
