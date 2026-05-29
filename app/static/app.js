const controls = document.querySelector("#controls");
const interactionForm = document.querySelector("#interactionForm");
const results = document.querySelector("#results");
const emptyState = document.querySelector("#emptyState");
const statusEl = document.querySelector("#status");
const precisionEl = document.querySelector("#precision");
const diversityEl = document.querySelector("#diversity");
const resultCountEl = document.querySelector("#resultCount");
const pageTitle = document.querySelector("#pageTitle");

const gradients = [
  ["#102a43", "#627d98"],
  ["#1f2933", "#cb6e17"],
  ["#243b53", "#2f855a"],
  ["#3c1742", "#9f7aea"],
  ["#1a365d", "#d69e2e"],
  ["#2d3748", "#e53e3e"],
  ["#234e52", "#38b2ac"],
  ["#322659", "#ed64a6"],
];

function setStatus(message, tone = "") {
  statusEl.textContent = message;
  statusEl.className = `status ${tone}`.trim();
}

function formValues() {
  const data = new FormData(controls);
  return {
    userId: data.get("userId") || "1",
    limit: data.get("limit") || "12",
    contextId: data.get("contextId") || "",
    mode: data.get("mode") || "hybrid",
    cacheType: data.get("cacheType") || "session",
  };
}

function endpointFor({ userId, limit, contextId, mode, cacheType }) {
  const path =
    mode === "content"
      ? `/recommend/${encodeURIComponent(userId)}/content`
      : mode === "collab"
        ? `/recommend/${encodeURIComponent(userId)}/collab`
        : `/recommend/${encodeURIComponent(userId)}`;
  const params = new URLSearchParams({ limit });
  if (contextId) params.set("context", contextId);
  if (mode === "hybrid") params.set("cache_type", cacheType);
  return `${path}?${params.toString()}`;
}

function posterStyle(movie) {
  const key = Number(movie.movieId || movie.id?.slice(-4) || 0);
  const pair = gradients[Math.abs(key) % gradients.length];
  return `background: linear-gradient(135deg, ${pair[0]}, ${pair[1]});`;
}

function formatScore(value) {
  const number = Number(value || 0);
  if (number >= 100) return number.toFixed(0);
  if (number >= 10) return number.toFixed(1);
  return number.toFixed(3);
}

function renderMovie(rec) {
  const movie = rec.item || {};
  const genres = movie.genres?.length ? movie.genres : movie.tags || [];
  const sources = rec.sources?.length ? rec.sources.join(", ") : rec.source || "ranked";
  const movieId = movie.movieId || movie.id || "";
  const safeTitle = movie.title || "Untitled Movie";

  return `
    <article class="movie-card">
      <div class="poster" style="${posterStyle(movie)}">
        <div class="poster-title">${safeTitle}</div>
      </div>
      <div class="movie-body">
        <div class="movie-meta">
          <span class="pill">#${movieId}</span>
          ${genres.slice(0, 3).map((genre) => `<span class="pill">${genre}</span>`).join("")}
        </div>
        <div class="score-line">
          <span>Score</span>
          <strong>${formatScore(rec.score)}</strong>
        </div>
        <div class="score-line">
          <span>Avg rating</span>
          <strong>${movie.avgRating ?? "--"}</strong>
        </div>
        <div class="score-line">
          <span>Source</span>
          <strong>${sources}</strong>
        </div>
        <div class="card-actions">
          <button type="button" data-action="context" data-movie-id="${movieId}">Use Context</button>
          <button type="button" data-action="rate" data-movie-id="${movieId}">Rate</button>
        </div>
      </div>
    </article>
  `;
}

async function loadMetrics(userId, limit) {
  try {
    const response = await fetch(`/metrics/${encodeURIComponent(userId)}?k=${encodeURIComponent(limit)}`);
    if (!response.ok) throw new Error("metrics failed");
    const metrics = await response.json();
    precisionEl.textContent = Number(metrics.precisionAtK).toFixed(3);
    diversityEl.textContent = Number(metrics.diversityScore).toFixed(3);
  } catch {
    precisionEl.textContent = "--";
    diversityEl.textContent = "--";
  }
}

async function loadRecommendations() {
  const values = formValues();
  pageTitle.textContent =
    values.mode === "content"
      ? "Content-Based Recommendations"
      : values.mode === "collab"
        ? "Collaborative Recommendations"
        : "Hybrid Recommendations";

  setStatus("Loading", "warn");
  results.innerHTML = "";
  emptyState.hidden = true;

  try {
    const [recommendationResponse] = await Promise.all([
      fetch(endpointFor(values)),
      loadMetrics(values.userId, values.limit),
    ]);
    if (!recommendationResponse.ok) {
      const error = await recommendationResponse.json().catch(() => ({}));
      throw new Error(error.detail || "request failed");
    }
    const payload = await recommendationResponse.json();
    resultCountEl.textContent = payload.count;
    results.innerHTML = payload.items.map(renderMovie).join("");
    emptyState.hidden = payload.items.length !== 0;
    setStatus("Ready", "ok");
  } catch (error) {
    resultCountEl.textContent = "--";
    emptyState.hidden = false;
    setStatus(error.message || "Error", "error");
  }
}

async function queueRating(event) {
  event.preventDefault();
  const { userId } = formValues();
  const movieId = document.querySelector("#interactionMovieId").value;
  const rating = Number(document.querySelector("#rating").value || 4.5);
  if (!movieId) {
    setStatus("Movie ID required", "error");
    return;
  }

  setStatus("Queueing", "warn");
  try {
    const response = await fetch("/interact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId, itemId: movieId, type: "rate", score: rating }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "queue failed");
    }
    setStatus("Queued", "ok");
  } catch (error) {
    setStatus(error.message || "Error", "error");
  }
}

controls.addEventListener("submit", (event) => {
  event.preventDefault();
  loadRecommendations();
});

interactionForm.addEventListener("submit", queueRating);

results.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const movieId = button.dataset.movieId;
  if (button.dataset.action === "context") {
    document.querySelector("#contextId").value = movieId;
    loadRecommendations();
  }
  if (button.dataset.action === "rate") {
    document.querySelector("#interactionMovieId").value = movieId;
    document.querySelector("#rating").focus();
  }
});

loadRecommendations();
