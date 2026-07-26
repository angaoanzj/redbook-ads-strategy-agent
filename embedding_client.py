"""Embedding client for note RAG recall.

Uses OpenAI-compatible `/embeddings` when AGENT_EMBEDDING_API_KEY is set;
otherwise a deterministic local hashing embedder so hybrid search still works offline/tests.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Sequence

import httpx

from model_config import load_embedding_config

LOCAL_MODEL = "local-hash-v1"
LOCAL_DIM = 256
_CJK_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        return vector
    return [value / norm for value in vector]


def local_hash_embed(text: str, *, dim: int = LOCAL_DIM) -> list[float]:
    """Bag-of-n-grams hashed into a fixed unit vector (offline fallback)."""
    vector = [0.0] * dim
    blob = (text or "").strip().lower()
    if not blob:
        return vector
    grams: list[str] = []
    for token in _CJK_RE.findall(blob):
        grams.append(token)
        if len(token) >= 2:
            for size in (2, 3):
                for index in range(0, len(token) - size + 1):
                    grams.append(token[index : index + size])
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return _l2_normalize(vector)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))


class EmbeddingClient:
    def __init__(self, config: dict[str, str] | None = None, *, transport: httpx.BaseTransport | None = None):
        self.config = config or load_embedding_config()
        self.transport = transport
        self.api_key = (self.config.get("api_key") or "").strip()
        self.base_url = (self.config.get("base_url") or "").rstrip("/")
        self.remote_model = self.config.get("model") or ""
        self.model = self.remote_model if self.api_key else LOCAL_MODEL
        self.backend = "remote" if self.api_key else "local"

    def embed_texts(self, texts: list[str]) -> tuple[list[list[float]], dict[str, Any]]:
        cleaned = [str(text or "").strip() or " " for text in texts]
        if not cleaned:
            return [], {"backend": self.backend, "model": self.model, "count": 0}
        if self.backend == "local" or not self.api_key:
            vectors = [local_hash_embed(text) for text in cleaned]
            return vectors, {
                "backend": "local",
                "model": LOCAL_MODEL,
                "count": len(vectors),
                "dim": LOCAL_DIM,
            }
        try:
            vectors = self._embed_remote(cleaned)
            return vectors, {
                "backend": "remote",
                "model": self.remote_model,
                "count": len(vectors),
                "dim": len(vectors[0]) if vectors else 0,
            }
        except Exception as exc:  # noqa: BLE001 — degrade to local, never block analyze
            vectors = [local_hash_embed(text) for text in cleaned]
            return vectors, {
                "backend": "local_fallback",
                "model": LOCAL_MODEL,
                "count": len(vectors),
                "dim": LOCAL_DIM,
                "error_type": exc.__class__.__name__,
            }

    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.remote_model, "input": texts}
        with httpx.Client(transport=self.transport, timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        items = sorted(data.get("data") or [], key=lambda row: int(row.get("index", 0)))
        vectors = [_l2_normalize([float(x) for x in row["embedding"]]) for row in items]
        if len(vectors) != len(texts):
            raise RuntimeError(f"embedding count mismatch: got {len(vectors)} want {len(texts)}")
        return vectors
