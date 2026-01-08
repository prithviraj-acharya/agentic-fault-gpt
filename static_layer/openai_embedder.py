# static_layer/openai_embedder.py
from __future__ import annotations

import os
from typing import List

from openai import OpenAI


class OpenAIEmbeddingFunction:
    """
    Chroma embedding-function adapter that calls OpenAI embeddings endpoint.
    Must be used consistently for BOTH indexing and querying.
    """

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"
        )
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=api_key)

    # Newer Chroma embedding protocol sometimes expects this flag.
    is_legacy: bool = False

    def is_legacy(self) -> bool:  # pragma: no cover
        return False

    def name(self) -> str:
        # This label is persisted by Chroma; keep stable.
        return f"openai-embeddings::{self.model}"

    def get_config(self) -> dict:
        return {"model": self.model}

    @classmethod
    def build_from_config(cls, config: dict) -> "OpenAIEmbeddingFunction":
        model = (config or {}).get("model")
        return cls(model=model)

    def validate_config(self, config: dict) -> None:
        if config is None:
            return
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")
        model = config.get("model")
        if model is not None and not isinstance(model, str):
            raise TypeError("config['model'] must be a str")

    def validate_config_update(self, old_config: dict, new_config: dict) -> None:
        self.validate_config(old_config)
        self.validate_config(new_config)

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> List[str]:
        return ["cosine", "l2", "ip"]

    def embed_with_retries(self, input: List[str], **_: object) -> List[List[float]]:
        return self.__call__(input=input)

    # Chroma EmbeddingFunction protocol (required by validate_embedding_function).
    # Must be exactly: __call__(self, input)
    def __call__(self, input: List[str]) -> List[List[float]]:
        return self.embed_documents(input=[str(x) for x in (input or [])])

    def embed_documents(self, input: List[str], **_: object) -> List[List[float]]:
        payload = input or []
        if not payload:
            return []
        resp = self.client.embeddings.create(model=self.model, input=payload)
        return [d.embedding for d in resp.data]

    def embed_query(self, input: str | List[str], **_: object) -> List[List[float]]:
        # Return type is always Embeddings (List[List[float]]) to match Chroma's protocol.
        if isinstance(input, list):
            payload = [str(x) for x in input]
        else:
            payload = [str(input)]
        resp = self.client.embeddings.create(model=self.model, input=payload)
        return [d.embedding for d in resp.data]
