# MovieLens Recommendation Engine

Hệ thống gợi ý phim end-to-end xây bằng **FastAPI + MongoDB Atlas/Atlas Local + Redis + React**, sử dụng dataset **MovieLens `ml-latest-small`**. Dự án được thiết kế để người chấm có thể thấy đầy đủ một pipeline recommendation thực tế: ingest dataset, mapping dữ liệu sang MongoDB, tạo embedding, xử lý interaction, cache, vector search, aggregation pipeline và hiển thị kết quả trên giao diện.

## 1. Bài Toán

Mục tiêu của dự án là gợi ý phim phù hợp cho từng người dùng dựa trên:

- Lịch sử rating và tương tác của user.
- Nội dung phim: title, genres, tags, description.
- Hành vi của các user tương tự.
- Xu hướng tương tác gần đây.
- Context hiện tại, ví dụ đang xem trang chi tiết của một phim.

Dự án giải quyết các vấn đề thường gặp trong recommender system:

- **Cold start**: user ít interaction sẽ fallback sang popular movies hoặc item-to-item recommendation theo context.
- **Data sparsity**: kết hợp content-based, collaborative, trending và hybrid để giảm phụ thuộc vào một nguồn dữ liệu duy nhất.
- **Personalization gần real-time**: interaction từ frontend được đưa vào Redis Stream, worker ghi vào MongoDB, cập nhật `user_profiles` và invalidate cache.
- **Diversity**: hybrid ranking dùng rerank và MMR để tránh danh sách gợi ý quá giống nhau.

## 2. Điểm Nổi Bật

- Dashboard React với các rail: Hybrid, Content-Based, Collaborative, Trending.
- Search phim bằng Atlas Search BM25, Atlas Vector Search hoặc hybrid search.
- Movie detail có feedback actions: rate, watch progress, complete, like, share, watchlist.
- Feature store nhẹ bằng collection `user_profiles`.
- Redis cache cho recommendation và popular search.
- Redis Stream + background worker cho interaction pipeline.
- MongoDB aggregation pipeline cho collaborative filtering và trending.
- MongoDB Atlas Vector Search cho semantic retrieval.
- Có fallback khi vector search, cache hoặc collaborative data không đủ tốt.

## 3. Tech Stack

| Layer | Công nghệ |
| --- | --- |
| Frontend | React 17, Vite |
| Backend API | Python, FastAPI |
| Database | MongoDB async bằng Motor |
| Vector Search | MongoDB Atlas `$vectorSearch` hoặc Atlas Local |
| Text Search | MongoDB Atlas Search `$search` |
| Cache | Redis |
| Queue | Redis Stream |
| Dataset | MovieLens `ml-latest-small` |
| Test | pytest |

## 4. Architecture

```text
                         +----------------------+
                         |     React Client      |
                         |----------------------|
                         | Dashboard rails       |
                         | Search page           |
                         | Movie detail          |
                         | Feedback controls     |
                         +----------+-----------+
                                    |
                                    | HTTP
                                    v
                         +----------------------+
                         |      FastAPI API      |
                         |----------------------|
                         | /search/*             |
                         | /recommend/*          |
                         | /interact/*           |
                         | /interactions/*       |
                         | /metrics/*            |
                         +----+-------------+---+
                              |             |
                    query/read|             |cache + queue
                              v             v
              +----------------------+   +----------------------+
              |       MongoDB         |   |        Redis         |
              |----------------------|   |----------------------|
              | users                |   | recommendation cache |
              | items                |   | popular cache        |
              | interactions         |   | interaction_events   |
              | user_profiles        |   +----------+-----------+
              | explorations         |              |
              +----------+-----------+              |
                         ^                          | xreadgroup
                         |                          v
                         |              +----------------------+
                         |              | Background Worker    |
                         |              |----------------------|
                         +--------------| insert interaction   |
                                        | update user profile  |
                                        | invalidate cache     |
                                        +----------------------+
```

### Luồng dữ liệu chính

```text
MovieLens CSV
  -> scripts/seed.py
  -> MongoDB: users, items, interactions, user_profiles
  -> FastAPI recommendation/search endpoints
  -> React dashboard/search/detail
  -> user interaction
  -> Redis Stream
  -> background worker
  -> MongoDB interactions + user_profiles update
  -> Redis cache invalidation
  -> recommendation refresh
```

## 5. Cấu Trúc Thư Mục

```text
app/
  core/
    config.py                 # cấu hình MongoDB, Redis, timeout, vector index
    database.py               # Mongo client, Redis client, index setup
  background/
    interaction_worker.py     # Redis Stream consumer
  models/
    schemas.py                # Pydantic schemas
  routes/
    recommendations.py        # /recommend endpoints
    interactions.py           # /interact và interaction summary
    search.py                 # /search endpoints
    metrics.py                # /metrics endpoint
    items.py                  # item endpoints
  services/
    recommendation/           # content, collaborative, hybrid, trending, rerank
    search.py                 # text/vector/hybrid movie search
    embeddings.py             # tạo embedding 1536 chiều
    cache.py                  # Redis cache helpers
    ids.py                    # resolve MovieLens id <-> Mongo ObjectId
scripts/
  seed.py                     # import MovieLens CSV vào MongoDB
client/
  src/
    components/               # dashboard, movie detail, search, watchlist
    styles/                   # CSS frontend
data/
  movies.csv
  ratings.csv
  tags.csv
  links.csv
tests/
```

## 6. Dataset Và Mapping

Dự án dùng MovieLens `ml-latest-small` của GroupLens.

| File | Vai trò |
| --- | --- |
| `movies.csv` | Danh mục phim: `movieId`, `title`, `genres` |
| `ratings.csv` | Rating 0.5 đến 5.0 sao: `userId`, `movieId`, `rating`, `timestamp` |
| `tags.csv` | Tag do user nhập: `userId`, `movieId`, `tag`, `timestamp` |
| `links.csv` | Mapping sang IMDb/TMDB: `movieId`, `imdbId`, `tmdbId` |

Quy mô dataset:

- 610 users.
- 9.742 movies.
- 100.836 ratings.
- 3.683 tag applications.

Mapping khi seed:

- `userId` của MovieLens được map sang `_id` trong collection `users`.
- `movieId` của MovieLens được map sang `_id` trong collection `items`.
- Mỗi dòng rating được chuyển thành interaction type `rate`.
- Rating `>= 3.5` được xem là positive signal để xây dựng user profile.
- Genres, user tags và inferred tags được hợp nhất thành `tags`.
- Title, genres, tags được dùng để tạo `description` và `embedding`.
- `links.csv` bổ sung `imdbId`, `tmdbId` cho item.

## 7. MongoDB Data Schema

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
  "description": "Forrest Gump (1994) genres: Comedy, Drama...",
  "embedding": [1536],
  "popularity": 24.1482,
  "avgRating": 4.1641,
  "ratingCount": 329,
  "businessMargin": 0,
  "available": true,
  "imdbId": "0109830",
  "tmdbId": 13,
  "createdAt": "datetime"
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

```json
{
  "_id": "ObjectId",
  "userId": "ObjectId",
  "movielensUserId": 1,
  "embedding": [1536],
  "interactionWeight": 1963,
  "updatedAt": "datetime"
}
```

`user_profiles` là feature store nhẹ. Vector của user được tính từ trung bình có trọng số của embedding các phim mà user có positive interaction.

## 8. Indexes Và Search Indexes

Normal MongoDB indexes:

- `users.movielensUserId` unique.
- `items.movieId` unique.
- `items.genres`, `items.tags`, `items.popularity`, `items.available`.
- `interactions.userId + itemId + timestamp`.
- `interactions.userId + type + score`.
- `user_profiles.userId` unique.

Atlas indexes:

- Vector Search index trên `items.embedding`, `1536` dimensions, cosine similarity.
- Text Search index trên `title`, `description`, `tags`, `genres`, `available`.

Các index được tạo trong `app/core/database.py` khi app start hoặc khi chạy seed.

## 9. Recommendation Logic

### 9.1. Content-Based Recommendation

Endpoint:

```text
GET /recommend/{userId}/content
```

Luồng xử lý:

```text
resolve user
  -> kiểm tra cold start
  -> lấy user_profiles.embedding
  -> lấy recent average embedding
  -> blend long-term vector và recent vector
  -> MongoDB $vectorSearch trên items.embedding
  -> loại item đã xem
  -> boost theo genre affinity
  -> boost theo context nếu có
  -> trả về recommendation
```

Pipeline chính:

```json
[
  {
    "$vectorSearch": {
      "index": "items_embedding_vector_index",
      "path": "embedding",
      "queryVector": "user_query_vector",
      "numCandidates": 100,
      "limit": 50
    }
  },
  {
    "$match": {
      "_id": {"$nin": "seen_ids"},
      "available": true
    }
  },
  {
    "$addFields": {
      "recScore": {"$meta": "vectorSearchScore"}
    }
  },
  {
    "$limit": 20
  }
]
```

Nếu user có dưới 3 interaction, hoặc không có vector hợp lệ, hệ thống fallback về context recommendation hoặc popular movies.

### 9.2. Collaborative Filtering

Endpoint:

```text
GET /recommend/{userId}/collab
```

Luồng xử lý:

```text
lấy positive items của user hiện tại
  -> tìm các user khác có overlap trên các item này
  -> tính similarity bằng weightedScore và overlap
  -> lấy positive items từ similar users
  -> loại item user hiện tại đã xem
  -> cộng điểm với time decay
  -> trả về top items
```

Aggregation tìm similar users:

```json
[
  {
    "$match": {
      "itemId": {"$in": "user_positive_item_ids"},
      "userId": {"$ne": "current_user_id"}
    }
  },
  {
    "$group": {
      "_id": "$userId",
      "overlap": {"$sum": 1},
      "similarity": {
        "$sum": {"$ifNull": ["$weightedScore", {"$ifNull": ["$score", 1]}]}
      }
    }
  },
  {
    "$addFields": {
      "similarity": {"$multiply": ["$similarity", "$overlap"]}
    }
  },
  {
    "$sort": {
      "similarity": -1,
      "overlap": -1
    }
  },
  {
    "$limit": 30
  }
]
```

Rating MovieLens chỉ được xem là positive khi `score >= 3.5`.

### 9.3. Trending Recommendation

Endpoint:

```text
GET /recommend/{userId}/trending
```

Trending dùng aggregation trên `interactions`:

```text
$match positive interactions trong window gần đây
  -> $group theo itemId
  -> tính interactionCount và totalScore
  -> $sort theo velocity
  -> $lookup sang items
  -> bỏ phim không available
  -> trả về top items
```

`impression` không được tính là positive signal. Nó chỉ phù hợp để đo exposure hoặc CTR.

### 9.4. Hybrid Recommendation

Endpoint:

```text
GET /recommend/{userId}
```

Hybrid là luồng recommendation chính trên dashboard:

```text
content candidates       collaborative candidates       context candidates
        |                         |                            |
        +-------------------------+----------------------------+
                                  |
                                  v
                       normalize per-source scores
                                  |
                                  v
                           weighted merge
                                  |
                                  v
                       multi-objective rerank
                                  |
                                  v
                    genre affinity + filtering layer
                                  |
                                  v
                         MMR diversity rerank
                                  |
                                  v
                    exploration replace + fill popular
                                  |
                                  v
                            API response
```

Trọng số mặc định:

- Content: `0.4`.
- Collaborative: `0.6`.

Nếu collaborative trả về quá ít candidate, hệ thống tăng content lên `0.8`. Nếu có `context`, ví dụ đang ở trang chi tiết phim, hệ thống ưu tiên item-to-item recommendation.

## 10. Search Logic

Endpoint:

```text
GET /search/movies?q=matrix&limit=20&mode=hybrid
```

Search có 3 mode:

- `text`: Atlas Search BM25 trên `title`, `description`, `tags`, `genres`.
- `vector`: embed query rồi chạy `$vectorSearch` trên `items.embedding`.
- `hybrid`: chạy cả text và vector, sau đó merge bằng Reciprocal Rank Fusion.

RRF score:

```text
score(item) = sum(1 / (k + rank_i))
```

Một phim được ưu tiên cao nếu vừa match keyword tốt vừa gần về semantic meaning.

## 11. Interaction Signals

| Event | Ý nghĩa | Weight |
| --- | --- | --- |
| `impression` | Phim được hiển thị | `0` |
| `click` | Click recommendation card | `2` |
| `search_click` | Click từ search result | `2.5` |
| `watch_start` | Bắt đầu xem | `3` |
| `watch_progress` | Tiến độ xem | `3.5 * completionRate` |
| `watch_complete` | Xem hết/gần hết | `6` |
| `rate` | Rating sao | `score * 2` |
| `watchlist_add` | Thêm vào watchlist | `4` |
| `watchlist_remove` | Gỡ khỏi watchlist | `-2` |
| `like` | Thích phim | `5` |
| `dislike` | Không thích phim | `-4` |
| `hide` | Ẩn phim | `-8` |
| `share` | Chia sẻ phim | `4` |

Các event không phải `impression` sẽ invalidate recommendation cache của user.

## 12. Cache Strategy

| Cache | Key pattern | TTL |
| --- | --- | --- |
| Hybrid session recommendation | `rec:{userId}:v9:session:*` | 60s |
| Hybrid offline recommendation | `rec:{userId}:v9:offline:*` | 3600s |
| Popular search | `search:popular:v1:*` | 300s |

Khi user gửi interaction:

```text
POST /interact/*
  -> enqueue Redis Stream
  -> invalidate rec:{userId}:*
  -> worker ghi MongoDB
  -> worker cập nhật user_profiles nếu signal positive
  -> frontend refresh recommendation rails
```

## 13. Cách Chạy Local

### 13.1. Cài Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Ví dụ `.env` local:

```env
MONGODB_URI=mongodb://localhost:27017/?directConnection=true
MONGODB_DB=recommendation
REDIS_URL=redis://localhost:6379/0
VECTOR_INDEX_NAME=items_embedding_vector_index
INFRA_TIMEOUT_MS=200
```

### 13.2. Start MongoDB Atlas Local và Redis

```bash
docker compose up -d
```

Lưu ý: `$vectorSearch` cần MongoDB Atlas hoặc image `mongodb/mongodb-atlas-local`. MongoDB Community thường không hỗ trợ `$vectorSearch`.

### 13.3. Seed MovieLens data

```bash
python scripts/seed.py
```

Seed mặc định là safe upsert: cập nhật users, movies, ratings, embeddings, tags và user profiles mà không xóa các field enrich như `items.poster`.

Reset sạch database khi cần:

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

### 13.4. Start API

```bash
uvicorn app.main:app --port=8080 --reload
```

API chạy tại:

```text
http://localhost:8080
```

### 13.5. Start background worker

Mở terminal khác:

```bash
python -m app.background.interaction_worker
```

Worker cần chạy để các interaction được ghi từ Redis Stream vào MongoDB.

### 13.6. Start frontend

```bash
cd client
npm install
npm run start
```

Frontend chạy tại:

```text
http://localhost:3000
```

## 14. API Quick Test

Health:

```bash
curl http://localhost:8080/health
```

Popular movies:

```bash
curl "http://localhost:8080/search/movies/popular?limit=5"
```

Hybrid search:

```bash
curl "http://localhost:8080/search/movies?q=matrix&limit=5&mode=hybrid"
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

Trending recommendation:

```bash
curl "http://localhost:8080/recommend/1/trending?limit=8"
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

## 15. Demo Cho Người Chấm

Flow demo đề xuất:

1. Mở dashboard tại `http://localhost:3000`.
2. Chọn `MovieLens user 1`, quan sát các rail recommendation.
3. Giải thích `For You` là hybrid recommendation.
4. Mở rail content-based để nói về Vector Search và `user_profiles.embedding`.
5. Mở rail collaborative để nói về aggregation pipeline tìm similar users.
6. Vào `/search`, tìm `matrix`, giải thích hybrid search BM25 + vector + RRF.
7. Mở một phim, xem interaction summary.
8. Rate 5 sao hoặc complete movie.
9. Giải thích event đi vào Redis Stream, worker ghi MongoDB và cập nhật user profile.
10. Quay lại dashboard, recommendation được refresh do cache bị invalidate.

Ba endpoint nên demo trực tiếp:

```text
GET /recommend/1/content?limit=10
GET /recommend/1/collab?limit=10
GET /recommend/1?limit=10
```

## 16. Tests

```bash
pytest
```

Tests hiện có kiểm tra:

- Route registration.
- Interaction payload aliases.
- Supported interaction types.
- Implicit feedback weighting.
- Time decay.
- Recommendation/reranking behavior.
- Embedding utilities.

## 17. Troubleshooting

### Interaction đã queued nhưng summary không đổi

Worker có thể chưa chạy:

```bash
python -m app.background.interaction_worker
```

### Recommendation bị stale

Đợi TTL hoặc invalidate cache user:

```bash
python -c "import asyncio; from app.services.cache import invalidate_user_cache; asyncio.run(invalidate_user_cache(1))"
```

### `$vectorSearch` lỗi

Đảm bảo đang dùng Atlas hoặc Atlas Local:

```bash
docker compose up -d
```

### Query local quá dễ fallback popular

Tăng timeout trong `.env`:

```env
INFRA_TIMEOUT_MS=1000
```

## 18. Dataset Credit

Dự án sử dụng MovieLens `ml-latest-small` của GroupLens. Khi trình bày học thuật hoặc public, trích dẫn theo hướng dẫn trong `data/README.txt`.
