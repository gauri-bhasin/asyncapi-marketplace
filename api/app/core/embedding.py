import hashlib
from typing import Iterable


def deterministic_embedding(text: str, dim: int = 128) -> list[float]:
    values = [0.0] * dim
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = digest[0] % dim
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        values[idx] += sign * (1.0 + digest[2] / 255.0)
    norm = sum(v * v for v in values) ** 0.5
    if norm == 0:
        return values
    return [v / norm for v in values]


def combine_text(parts: Iterable[str]) -> str:
    return " | ".join(part for part in parts if part).strip()
