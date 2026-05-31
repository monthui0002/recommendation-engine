from app.main import app


def test_recommendation_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/" in paths
    assert "/recommend/{user_id}" in paths
    assert "/recommend/{user_id}/content" in paths
    assert "/recommend/{user_id}/collab" in paths
    assert "/interact" in paths
    assert "/interact/{interaction_type}" in paths
    assert "/search/movies/imdb/{imdb_id}" in paths
    assert "/search/movies/popular" in paths
    assert "/interactions/{user_id}/items/{item_id}/summary" in paths
