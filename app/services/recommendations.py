"""
Compatibility facade for recommendation services.

The implementation is split across app.services.recommendation.* modules so each
layer stays readable: signals, common queries, content, collaborative, hybrid,
filters, reranking, affinity and trending.
"""

from app.services.recommendation import *  # noqa: F401,F403
