# MovieLens Recommendation Engine

Một hệ thống recommendation cho phim, xây bằng **FastAPI + MongoDB + Redis + React**, dùng dataset **MovieLens `ml-latest-small`** của GroupLens.

Project này được thiết kế để trình bày như một hệ thống recommendation end-to-end:

- Search movie catalog với trang search riêng.
- Recommendation rails: Hybrid, Content-Based, Collaborative, Trending.
- Movie detail có feedback actions: rate, watch progress, complete, share.
- Real-time interaction pipeline qua Redis Stream + background worker.
- Feature Store nhẹ bằng `user_profiles`.
- Cache Redis cho recommendation và popular movies.
- MongoDB Atlas Vector Search hoặc Atlas Local cho vector retrieval.

## Demo Highlights

Khi trình bày, có thể đi theo flow này:

1. Mở dashboard: xem các rail recommendation cho `MovieLens user 1`.
2. Chuyển user id: recommendation thay đổi theo lịch sử user.
3. Vào `/search`: chưa nhập gì sẽ thấy popular movies được cache.
4. Search một phim: kết quả hiện ngay từ backend, poster enrich sau.
5. Bấm vào một phim: detail page hiện interaction summary của user.
6. Rate 5 sao, Start/Complete watch, Share.
7. Quay lại dashboard: rails tự refresh, cache bị invalidate.
8. Giải thích vì sao `impression` không làm tăng điểm, chỉ dùng cho CTR/exposure.

## Architecture

```text
React Client
  |-- Dashboard rails
  |-- Search page
  |-- Movie detail + feedback controls
          |
          v
FastAPI
  |-- /search/*          -> search + popular cache
  |-- /recommend/*       -> content/collab/hybrid/trending
  |-- /interact/*        -> enqueue interaction events
  |-- /interactions/*    -> per-movie user interaction summary
  |-- /metrics/*         -> mock Precision@K + diversity
          |
          +------------------ Redis
          |                    |-- rec cache
          |                    |-- popular cache
          |                    |-- interaction_events stream
          |
          +------------------ MongoDB Atlas / Atlas Local
                               |-- users
                               |-- items
                               |-- interactions
                               |-- user_profiles
                               |-- explorations

Background worker
  Redis Stream -> insert interaction -> update user profile -> invalidate cache
```

## Tech Stack

| Layer | Tech |
| --- | --- |
| API | Python 3, FastAPI |
| Database | MongoDB async via Motor |
| Vector Search | MongoDB Atlas `$vectorSearch` |
| Cache | Redis async |
| Queue | Redis Stream |
| Frontend | React 17 + Vite |
| Dataset | MovieLens `ml-latest-small` |
| Tests | pytest |

## Folder Structure

```text
app/
  core/
    config.py                 # Pydantic settings
    database.py               # Mongo + Redis clients, indexes
  background/
    interaction_worker.py     # Redis Stream consumer
  models/
    schemas.py                # Pydantic schemas
  routes/
    recommendations.py        # /recommend endpoints
    interactions.py           # /interact + interaction summary
    search.py                 # /search endpoints
    metrics.py                # /metrics endpoint
  services/
    recommendations.py        # core ranking logic
    search.py                 # hybrid search
    cache.py                  # Redis helpers
    embeddings.py             # deterministic mock embeddings
    ids.py                    # MovieLens id <-> Mongo ObjectId
scripts/
  seed.py                     # import MovieLens CSV
client/
  src/
    components/               # dashboard, search, movie detail
    styles/                   # production-ish dark UI
data/
  movies.csv
  ratings.csv
  tags.csv
  links.csv
tests/
```

## Data Model

### `users`

```json
{
  "_id": "ObjectId",
  "movielensUserId": 1,
  "name": "MovieLens User 1",
  "preferences": ["Drama", "Comedy"],
  "createdAt": "datetime"
}
```

### `items`

```json
{
  "_id": "ObjectId",
  "movieId": 356,
  "title": "Forrest Gump (1994)",
  "type": "movie",
  "genres": ["Comedy", "Drama", "Romance", "War"],
  "tags": ["Comedy", "Drama", "heartwarming"],
  "description": "Forrest Gump (1994) genres: ...",
  "embedding": [1536 numbers],
  "popularity": 24.1482,
  "avgRating": 4.1641,
  "ratingCount": 329,
  "available": true,
  "imdbId": "0109830",
  "tmdbId": 13
}
```

### `interactions`

```json
{
  "_id": "ObjectId",
  "userId": "ObjectId",
  "itemId": "ObjectId",
  "movielensUserId": 1,
  "movieId": 356,
  "type": "rate",
  "score": 5,
  "completionRate": 1,
  "weightedScore": 10,
  "source": "detail_page",
  "timestamp": "datetime"
}
```

### `user_profiles`

Feature Store nhẹ. Worker cập nhật vector này khi có positive signal.

```json
{
  "_id": "ObjectId",
  "userId": "ObjectId",
  "movielensUserId": 1,
  "embedding": [1536 numbers],
  "interactionWeight": 1963,
  "updatedAt": "datetime"
}
```

## Recommendation Logic

### 1. Content-Based

Endpoint:

```text
GET /recommend/{userId}/content
```

Flow:

```text
resolve user
  -> read long-term user_profiles.embedding
  -> blend with recent positive interactions
  -> MongoDB $vectorSearch
  -> local vector fallback if Atlas vector search unavailable
  -> genre/tag affinity boost
  -> context boost if ?context=movieId
```

Nếu user quá ít interaction hoặc vector search chậm, hệ thống fallback về popular movies.

### 2. Collaborative Filtering

Endpoint:

```text
GET /recommend/{userId}/collab
```

Flow:

```text
positive items of current user
  -> find users with overlap
  -> group similar users
  -> collect positive items from similar users
  -> weighted score + time decay
```

Rating MovieLens chỉ được xem là positive khi `score >= 3.5`.

### 3. Hybrid

Endpoint:

```text
GET /recommend/{userId}
```

Flow:

```text
content candidates       collaborative candidates
        |                         |
        +-----------+-------------+
                    v
           normalize per-source scores
                    v
           weighted merge
                    v
           multi-objective rerank
                    v
           filtering + diversity + exploration
                    v
              API response
```

Default:

```text
content = 40%
collaborative = 60%
```

Nếu collaborative quá ít candidate, content tăng lên `80%`.

### 4. Trending

Endpoint:

```text
GET /recommend/{userId}/trending
```

Trending dựa trên interaction velocity gần đây, bỏ qua `impression` vì impression chỉ là exposure.

## Interaction Signals

| Event | Meaning | Weight |
| --- | --- | --- |
| `impression` | Movie được hiển thị cho user | `0` |
| `click` | User click recommendation card | `2` |
| `search_click` | User click từ search results | `2.5` |
| `watch_start` | Bắt đầu xem | `3` |
| `watch_progress` | Tiến độ xem | `3.5 * completionRate` |
| `watch_complete` | Xem gần hết/hết phim | `6` |
| `rate` | Rating sao | `score * 2` |
| `watchlist_add` | Thêm vào watchlist | `4` |
| `watchlist_remove` | Gỡ khỏi watchlist | `-2` |
| `like` | Muốn thấy phim tương tự | `5` |
| `dislike` | Giảm phim tương tự | `-4` |
| `hide` | Ẩn phim này | `-8` |
| `share` | Chia sẻ phim | `4` |

`impression` rất quan trọng cho production vì là mẫu số của CTR và giúp tạo negative sample kiểu “seen but ignored”. Tuy nhiên nó không được dùng như positive preference.

## Frontend Features

### Dashboard

- `For You`: hybrid recommendation.
- `Similar To Your Taste`: content profile.
- `Users Also Liked`: collaborative filtering.
- `Trending Now`: recent engagement.
- Metrics cards: Precision@K mock, diversity, item counts.

### Search Page

Route:

```text
/search
```

- Khi chưa search: hiển thị popular movies.
- Popular được cache Redis trong vài phút.
- Khi search: backend result render trước, poster từ OMDB enrich sau.
- Movie không có poster sẽ có placeholder MovieLens.

### Movie Detail

- Hiển thị rating/progress/share summary của user cho phim hiện tại.
- Có controls:
  - Start
  - Log Progress
  - Complete
  - Star rating
  - Remove Watchlist
  - Share
- Có context recommendation: `GET /recommend/{userId}?context={movieId}`.

## Cache Strategy

| Cache | Key pattern | TTL |
| --- | --- | --- |
| Hybrid session rec | `rec:{userId}:v6:session:*` | 60s |
| Hybrid offline rec | `rec:{userId}:v6:offline:*` | 3600s |
| Popular search | `search:popular:v1:*` | 300s |

Khi có non-impression interaction:

```text
POST /interact/*
  -> enqueue Redis Stream
  -> invalidate rec:{userId}:*
  -> FE refresh recommendation rails
```

Worker cũng invalidate cache sau khi ghi MongoDB.

## Running Locally

### 1. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For local Docker, `.env` can use:

```env
MONGODB_URI=mongodb://localhost:27017/?directConnection=true
MONGODB_DB=recommendation
REDIS_URL=redis://localhost:6379/0
VECTOR_INDEX_NAME=items_embedding_vector_index
INFRA_TIMEOUT_MS=200
```

### 2. Start MongoDB Atlas Local and Redis

```bash
docker compose up -d
```

Important: `$vectorSearch` requires MongoDB Atlas or `mongodb/mongodb-atlas-local`. MongoDB Community does not support `$vectorSearch`.

### 3. Seed MovieLens data

```bash
python scripts/seed.py
```

By default this is a safe upsert. It updates MovieLens users, movies, ratings,
embeddings, tags and user profiles without deleting existing enriched fields
such as `items.poster`, and without deleting live user interactions created from
the UI.

Use reset only when you intentionally want a clean database:

```bash
python scripts/seed.py --reset
```

Expected output:

```text
MovieLens upsert complete
Users: 610
Movies: 9742
Ratings/interactions: 100836
User profiles: 610
Example MovieLens userId: 1
Example MovieLens movieId: 1
```

### 4. Start API

```bash
uvicorn app.main:app --port=8080 --reload
```

API:

```text
http://localhost:8080
```

### 5. Start worker

Open another terminal:

```bash
python -m app.background.interaction_worker
```

Worker is required for queued interactions to be written to MongoDB.

### 6. Start frontend

```bash
cd client
npm install
npm run start
```

Frontend:

```text
http://localhost:3000
```

## API Quick Test

Health:

```bash
curl http://localhost:8080/health
```

Popular movies:

```bash
curl "http://localhost:8080/search/movies/popular?limit=5"
```

Search:

```bash
curl "http://localhost:8080/search/movies?q=matrix&limit=5"
```

Hybrid recommendation:

```bash
curl "http://localhost:8080/recommend/1?limit=8"
```

Content recommendation:

```bash
curl "http://localhost:8080/recommend/1/content?limit=8"
```

Collaborative recommendation:

```bash
curl "http://localhost:8080/recommend/1/collab?limit=8"
```

Context recommendation:

```bash
curl "http://localhost:8080/recommend/1?limit=8&context=356"
```

Interaction summary:

```bash
curl "http://localhost:8080/interactions/1/items/356/summary"
```

Rate movie:

```bash
curl -X POST http://localhost:8080/interact/rate \
  -H "Content-Type: application/json" \
  -d '{"userId":1,"itemId":356,"score":5,"source":"demo"}'
```

Watch progress:

```bash
curl -X POST http://localhost:8080/interact/watch_progress \
  -H "Content-Type: application/json" \
  -d '{"userId":1,"itemId":356,"completionRate":0.75,"source":"demo"}'
```

Metrics:

```bash
curl "http://localhost:8080/metrics/1?k=10"
```

## Presentation Script

Use this order in a live demo:

1. **Dataset**: MovieLens users, movies, ratings, tags.
2. **Architecture**: FastAPI, MongoDB, Redis cache, Redis Stream worker.
3. **Search**: Open `/search`; popular appears before any query.
4. **Search query**: Search `matrix`, explain hybrid search + poster enrichment.
5. **Detail page**: Open a movie, show current rating/watch summary.
6. **Feedback loop**: Rate 5 stars, Complete, Share.
7. **Worker**: Explain event is queued, worker updates interactions and profile.
8. **Recommendation refresh**: Go back to dashboard and show rails refresh.
9. **Algorithm**: Explain Content, Collaborative, Hybrid, Trending.
10. **Production concerns**: cache, timeout fallback, exploration, negative signals.

## Troubleshooting

### `/interact` returns queued but summary does not change

Worker is probably not running:

```bash
python -m app.background.interaction_worker
```

### Recommendations look stale

Clear Redis cache for current user or wait TTL:

```bash
python -c "import asyncio; from app.services.cache import invalidate_user_cache; asyncio.run(invalidate_user_cache(1))"
```

### `$vectorSearch` fails

Use Atlas or Atlas Local:

```bash
docker compose up -d
```

### Local recommendation query is slow

Increase:

```env
INFRA_TIMEOUT_MS=1000
```

The app still has fallbacks, but low timeouts can force popularity-based results.

## Tests

```bash
pytest
```

Current tests cover:

- supported interaction types.
- watch progress payload aliases.
- implicit feedback weighting.
- time decay.
- reranking.
- route registration.

## Dataset Credit

This project uses MovieLens `ml-latest-small` from GroupLens. For academic or public presentation, cite GroupLens according to `data/README.txt`.
