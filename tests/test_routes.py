from app.main import app


def test_recommendation_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/" in paths
    assert "/recommend/{user_id}" in paths
    assert "/recommend/{user_id}/content" in paths
    assert "/recommend/{user_id}/collab" in paths
