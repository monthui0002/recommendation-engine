import hashlib
import random


def get_embedding(text: str) -> list[float]:
    # Placeholder for OpenAI/Cohere embeddings. The text-seeded RNG keeps tests repeatable.
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def average_embeddings(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    size = len(vectors[0])
    return [sum(vector[i] for vector in vectors) / len(vectors) for i in range(size)]
