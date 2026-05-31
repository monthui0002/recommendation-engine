from app.services.embeddings import get_embedding, inferred_tags
from app.services.recommendation.common import cosine_similarity


def test_mock_embeddings_keep_franchise_movies_close() -> None:
    avengers = get_embedding("The Avengers Action Adventure Sci-Fi")
    iron_man = get_embedding("Iron Man Action Adventure Sci-Fi")
    romance = get_embedding("Pride and Prejudice Drama Romance")

    assert cosine_similarity(avengers, iron_man) > cosine_similarity(avengers, romance)


def test_inferred_tags_detect_marvel_context() -> None:
    tags = inferred_tags("Avengers: Infinity War Action Adventure Sci-Fi")

    assert "marvel" in tags
    assert "mcu" in tags
