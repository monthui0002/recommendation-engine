import hashlib
import math
import re


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "part",
    "movie",
    "film",
}
_FRANCHISE_ALIASES = {
    "marvel": {
        "ant man",
        "avengers",
        "black panther",
        "captain america",
        "doctor strange",
        "guardians of the galaxy",
        "hulk",
        "iron man",
        "marvel",
        "spider man",
        "spiderman",
        "thor",
        "wolverine",
        "x men",
        "xmen",
    },
    "star wars": {"star wars"},
    "lord of the rings": {"hobbit", "lord of the rings"},
    "harry potter": {"fantastic beasts", "harry potter"},
    "batman": {"batman", "dark knight"},
    "superman": {"superman"},
}


def semantic_tokens(text: str) -> list[str]:
    normalized = text.lower().replace("-", " ")
    tokens = [
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in _STOPWORDS and not token.isdigit()
    ]
    token_set = set(tokens)

    for franchise, aliases in _FRANCHISE_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            token_set.add(franchise)
            token_set.add("franchise")
            if franchise == "marvel":
                token_set.update({"mcu", "superhero", "comic"})

    return sorted(token_set)


def inferred_tags(text: str) -> list[str]:
    return [
        token
        for token in semantic_tokens(text)
        if token in _FRANCHISE_ALIASES or token in {"mcu", "superhero", "comic", "franchise"}
    ]


def get_embedding(text: str) -> list[float]:
    """
    Placeholder for real embeddings.

    Instead of pure random vectors, use deterministic feature hashing so shared
    title/genre/tag/franchise tokens land near each other in vector space.
    """
    vector = [0.0] * 1536
    tokens = semantic_tokens(text)
    if not tokens:
        tokens = [text.lower()]

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        primary = int.from_bytes(digest[:4], "big") % 1536
        secondary = int.from_bytes(digest[4:8], "big") % 1536
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        vector[primary] += 1.0
        vector[secondary] += 0.35 * sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def average_embeddings(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    size = len(vectors[0])
    return [sum(vector[i] for vector in vectors) / len(vectors) for i in range(size)]
