# MovieLens Recommendation Engine

Recommendation Engine cho phim, xây bằng **FastAPI + MongoDB + Redis**, sử dụng dữ liệu **MovieLens `ml-latest-small`** đã unzip trong thư mục `data/`.

Project này mô phỏng một hệ thống recommendation tương đối đầy đủ:

- Content-Based Filtering bằng MongoDB Atlas Vector Search.
- Collaborative Filtering bằng MongoDB Aggregation Pipeline.
- Hybrid ranking kết hợp content + collaborative.
- Feature Store nhẹ bằng collection `user_profiles`.
- Redis cache cho API recommendation.
- Redis Stream queue cho real-time interaction events.
- Worker nền để ghi interaction, cập nhật profile và invalidate cache.
- Fallback/circuit breaker để API vẫn trả kết quả khi vector search/cache chậm.

## Architecture

```text
                    ┌────────────────────────────┐
                    │        Client / curl        │
                    └──────────────┬─────────────┘
                                   │
                                   ▼
                         ┌─────────────────┐
                         │     FastAPI     │
                         │   app/main.py   │
                         └───────┬─────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐        ┌───────────────┐        ┌────────────────┐
│ /recommend/*  │        │   /interact   │        │   /metrics/*   │
│ routes        │        │   routes      │        │   routes       │
└───────┬───────┘        └───────┬───────┘        └───────┬────────┘
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐        ┌───────────────┐        ┌────────────────┐
│ Redis Cache   │        │ Redis Stream  │        │ Metrics        │
│ rec:{user}:*  │        │ interaction   │        │ mock + diversity│
└───────┬───────┘        └───────┬───────┘        └────────────────┘
        │                        │
        ▼                        ▼
┌────────────────────────────────────────┐
│        Recommendation Services          │
│ content, collaborative, hybrid, filter  │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│ MongoDB / Atlas Local                   │
│ users, items, interactions, profiles    │
│ $vectorSearch + aggregation pipeline    │
└────────────────────────────────────────┘

Redis Stream Worker:

POST /interact -> xadd Redis Stream -> worker consumes -> MongoDB insert
                                            -> update user_profiles
                                            -> invalidate Redis cache
```

## Tech Stack

- Runtime: Python 3 + FastAPI
- Database: MongoDB async qua `motor`
- Vector Search: MongoDB Atlas `$vectorSearch` trên `items.embedding`
- Cache: Redis async qua `redis.asyncio`
- Queue: Redis Stream
- Data source: GroupLens MovieLens `ml-latest-small`
- Tests: `pytest`

## Project Structure

```text
app/
  core/
    config.py                  # Pydantic Settings, đọc .env
    database.py                # Motor client, Redis client, Mongo indexes
  background/
    interaction_worker.py      # Consumer Redis Stream, ghi MongoDB, update profile
  models/
    schemas.py                 # Pydantic schemas
  routes/
    recommendations.py         # /recommend endpoints
    interactions.py            # /interact endpoint
    metrics.py                 # /metrics endpoint
  services/
    cache.py                   # Redis cache wrapper
    embeddings.py              # Mock embedding 1536 chiều
    ids.py                     # Resolve MovieLens numeric id -> Mongo ObjectId
    metrics.py                 # Precision@K mock + diversity
    recommendations.py         # Main recommendation logic
    timeouts.py                # Timeout wrapper
  utils.py
scripts/
  seed.py                      # Import MovieLens CSV vào MongoDB
data/
  movies.csv
  ratings.csv
  tags.csv
  links.csv
tests/
```

## Data Model

### `users`

MovieLens không có thông tin nhân khẩu học thật, nên user được tạo từ `ratings.csv` và `tags.csv`.

```json
{
  "_id": "ObjectId",
  "movielensUserId": 1,
  "name": "MovieLens User 1",
  "age": 0,
  "preferences": ["Comedy", "Adventure"],
  "createdAt": "datetime"
}
```

### `items`

Mỗi movie trong `movies.csv` trở thành một item.

```json
{
  "_id": "ObjectId",
  "movieId": 1,
  "title": "Toy Story (1995)",
  "type": "movie",
  "genres": ["Adventure", "Animation", "Children", "Comedy", "Fantasy"],
  "tags": ["Adventure", "Animation", "funny"],
  "description": "Toy Story (1995) genres: ...",
  "embedding": [0.12, -0.04],
  "popularity": 18.42,
  "avgRating": 3.92,
  "ratingCount": 215,
  "available": true,
  "imdbId": "0114709",
  "tmdbId": 862,
  "createdAt": "datetime"
}
```

### `interactions`

MovieLens ratings được map thành interaction `type="rate"`.

```json
{
  "_id": "ObjectId",
  "userId": "ObjectId",
  "itemId": "ObjectId",
  "movielensUserId": 1,
  "movieId": 1,
  "type": "rate",
  "score": 4.0,
  "weightedScore": 8.0,
  "timestamp": "datetime"
}
```

### `user_profiles`

Feature Store nhẹ. Mỗi user có một vector đại diện cho sở thích dài hạn.

```json
{
  "_id": "ObjectId",
  "userId": "ObjectId",
  "movielensUserId": 1,
  "embedding": [0.03, 0.91],
  "interactionWeight": 320.0,
  "updatedAt": "datetime"
}
```

## Indexes

App tạo một số index khi startup:

- `users.movielensUserId`
- `items.movieId`
- `items.popularity`
- `items.available + items.popularity`
- `items.tags`
- `items.genres`
- `interactions.userId + interactions.itemId + interactions.timestamp`
- `user_profiles.userId`

Vector Search index cần có trên `items.embedding`:

```json
{
  "name": "items_embedding_vector_index",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 1536,
        "similarity": "cosine"
      }
    ]
  }
}
```

> Quan trọng: `$vectorSearch` cần MongoDB Atlas hoặc Docker image `mongodb/mongodb-atlas-local`. MongoDB Community truyền thống không chạy được `$vectorSearch`.

## Recommendation Flow

### 1. Content-Based Filtering

Endpoint:

```text
GET /recommend/{userId}/content
```

Flow:

```text
userId
  -> resolve MovieLens userId hoặc Mongo ObjectId
  -> đọc user_profiles.embedding
  -> $vectorSearch trên items.embedding
  -> loại item user đã xem/rate
  -> context boost nếu có ?context=movieId
```

Nếu user chưa đủ interaction hoặc không có profile, service fallback về top popular movies.

### 2. Collaborative Filtering

Endpoint:

```text
GET /recommend/{userId}/collab
```

Flow:

```text
user ratings
  -> lookup users khác cùng rate movie
  -> group overlap để tính similar users
  -> lấy phim mà similar users thích
  -> tính weighted score + time decay
```

Rating được quy đổi theo implicit feedback:

```text
view     = 1
click    = 2
purchase = 5
rate     = rating * 2
```

Với MovieLens, dữ liệu chính là `rate`.

### 3. Hybrid Recommendation

Endpoint:

```text
GET /recommend/{userId}
```

Flow:

```text
content recommendations      collaborative recommendations
          │                              │
          └──────────────┬───────────────┘
                         ▼
                  weighted merge
                         ▼
               multi-objective reranking
                         ▼
                 filtering layer
                         ▼
              epsilon-greedy exploration
                         ▼
                    API response
```

Default weights:

```text
content       = 40%
collaborative = 60%
```

Nếu collaborative trả ít hơn 5 kết quả, content tăng lên 80%.

### 4. Session Intent

Nếu user tương tác ít nhất 3 phim có cùng tag/genre trong 5 phút gần nhất:

- content weight được tăng.
- item có tag/genre trùng session intent được boost trong reranking.

### 5. Multi-Objective Ranking

Final score được rerank theo công thức gần đúng:

```text
finalScore =
  hybridScore
  * (1 + businessMargin)
  * (1 + freshnessBoost)
  * sessionIntentBoost
```

Với MovieLens, `businessMargin` mặc định bằng `0`, vì đây là dataset nghiên cứu không có dữ liệu thương mại.

### 6. Filtering Layer

Trước khi trả API:

- loại movie `available=false`.
- loại movie user đã tương tác trong 7 ngày gần nhất.

### 7. Exploration

10% request sẽ thay 1 slot bằng một movie ngẫu nhiên ngoài nhóm top popularity. Mục đích là giảm feedback loop và tăng khám phá.

Log được lưu vào collection `explorations`.

## Real-Time Interaction Flow

Endpoint:

```text
POST /interact
```

API không ghi MongoDB trực tiếp. Thay vào đó:

```text
POST /interact
  -> validate payload
  -> xadd Redis Stream
  -> return {"status": "queued"}
```

Worker:

```text
Redis Stream event
  -> resolve userId/movieId
  -> insert interactions
  -> update user_profiles embedding
  -> invalidate Redis cache rec:{userId}:*
```

Lý do tách worker:

- giảm latency cho API write.
- tránh write bottleneck khi traffic interaction lớn.
- gom logic update profile/cache vào background pipeline.

## Cache Strategy

Hybrid recommendation có cache Redis.

Key format:

```text
rec:{userId}:{cacheType}:limit={limit}:context={context}
```

TTL:

```text
session = 60s
offline = 3600s
```

Khi có interaction mới, worker invalidate:

```text
rec:{userId}:*
```

Nếu Redis chậm hoặc lỗi, API bỏ qua cache và compute trực tiếp.

## Timeout / Circuit Breaker

Các thao tác hạ tầng quan trọng được bọc timeout mặc định `200ms`:

- Redis get/set/scan/delete
- MongoDB vector search
- MongoDB aggregation/query chính

Nếu timeout:

- content-based fallback local vector search hoặc popular movies.
- collaborative trả rỗng để hybrid tự giảm weight.
- cache bị bỏ qua.
- API ưu tiên có response hơn là chờ quá lâu.

Config trong `.env`:

```env
INFRA_TIMEOUT_MS=200
```

## Setup

### 1. Cài dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Chạy MongoDB Atlas Local và Redis

```bash
docker compose up -d
```

### 3. Import MovieLens data

```bash
python scripts/seed.py
```

Script sẽ xóa các collection hiện tại rồi import lại dữ liệu từ `data/`.

Output mẫu:

```text
MovieLens seed complete
Users: 610
Movies: 9742
Ratings/interactions: 100836
User profiles: 610
Example MovieLens userId: 1
Example MovieLens movieId: 1
```

### 4. Start API

```bash
uvicorn app.main:app --reload
```

UI dashboard sẽ có tại:

```text
http://localhost:8000/
```

### 5. Start worker

Mở terminal khác:

```bash
python -m app.background.interaction_worker
```

## API Examples

Các endpoint nhận được cả Mongo ObjectId và MovieLens numeric id. Ví dụ dưới đây dùng MovieLens id.

### Health

```bash
curl http://localhost:8000/health
```

### Hybrid recommendation

```bash
curl "http://localhost:8000/recommend/1?limit=10"
```

### Content-based only

```bash
curl "http://localhost:8000/recommend/1/content?limit=10"
```

### Collaborative only

```bash
curl "http://localhost:8000/recommend/1/collab?limit=10"
```

### Session context boost

Boost các movie giống movie context `movieId=1`.

```bash
curl "http://localhost:8000/recommend/1?limit=10&context=1"
```

### Offline cache TTL

```bash
curl "http://localhost:8000/recommend/1?limit=10&cache_type=offline"
```

### Record interaction

```bash
curl -X POST http://localhost:8000/interact \
  -H "Content-Type: application/json" \
  -d '{"userId":1,"itemId":1,"type":"rate","score":4.5}'
```

Response:

```json
{
  "status": "queued",
  "eventId": "1710000000000-0",
  "userId": "1",
  "itemId": "1"
}
```

### Metrics

```bash
curl "http://localhost:8000/metrics/1?k=10"
```

Metrics hiện tại gồm:

- `precisionAtK`: mock vì chưa có offline evaluation split.
- `diversityScore`: tính từ độ đa dạng tag/genre trong các item user tương tác gần đây.

## Local Data Import Details

Importer xử lý MovieLens như sau:

- `movies.csv`
  - tạo `items`.
  - parse `genres` từ chuỗi `Adventure|Comedy`.
- `ratings.csv`
  - tạo `users`.
  - tạo `interactions` loại `rate`.
  - tính `avgRating`, `ratingCount`, `popularity`.
- `tags.csv`
  - gom free-text tags cho từng movie.
  - đưa tags vào `items.tags` để content/session intent dùng.
- `links.csv`
  - map `imdbId`, `tmdbId`.

Embedding hiện đang mock bằng vector random deterministic 1536 chiều dựa trên text:

```text
title + genres + tags
```

Trong production có thể thay bằng OpenAI/Cohere embedding thật tại:

```text
app/services/embeddings.py
```

## Tests

```bash
pytest
```

Hiện tests kiểm tra:

- implicit feedback weighting.
- time decay.
- naive/aware datetime compatibility.
- multi-objective reranking.
- recommendation routes được register.

## Troubleshooting

### `$vectorSearch` không chạy

Bạn đang dùng MongoDB Community thường. Hãy dùng:

```bash
docker compose up -d
```

Compose file dùng image:

```text
mongodb/mongodb-atlas-local:latest
```

### API trả popular movies thay vì vector recommendations

Có thể do:

- chưa chạy `python scripts/seed.py`.
- chưa có vector index.
- MongoDB Atlas Local chưa sẵn sàng.
- timeout 200ms quá thấp với máy local.

Thử tăng:

```env
INFRA_TIMEOUT_MS=1000
```

### `/interact` trả queued nhưng dữ liệu chưa cập nhật

Kiểm tra worker đã chạy chưa:

```bash
python -m app.background.interaction_worker
```

## Notes

MovieLens `ml-latest-small` là dataset phục vụ development/education. Nếu dùng cho báo cáo hoặc publication, hãy đọc kỹ license trong `data/README.txt` và cite GroupLens theo hướng dẫn của họ.
