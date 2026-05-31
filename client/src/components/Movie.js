import React, { useContext, useEffect, useRef, useState } from "react";
import axios from "axios";
import Loading from "./Loading";
import Movies from "./Movies";
import { useParams } from "react-router-dom";
import "../styles/Movie.css";
import { API_ENDPOINT, AppContext, BACKEND_URL, normalizeRecItem, toOmdbId } from "../context";

const Movie = () => {
  const [movieDetails, setMovieDetails] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [similarMovies, setSimilarMovies] = useState([]);
  const [simsLoading, setSimsLoading] = useState(false);
  const [watchlisted, setWatchlisted] = useState(false);
  const [userRating, setUserRating] = useState(0);   // 0 = not rated
  const [hoverRating, setHoverRating] = useState(0);
  const { id } = useParams();
  const [currentMovie, setCurrentMovie] = useState(null);
  const [contextRecs, setContextRecs] = useState([]);
  const [contextLoading, setContextLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [ratingValue, setRatingValue] = useState(4);
  const [isWatching, setIsWatching] = useState(false);
  const [actionStatus, setActionStatus] = useState("");
  const [interactionSummary, setInteractionSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const trackedClickRef = useRef(null);
  const { userId, movies, hybridRecs, contentRecs, collabRecs, trendingRecs, trackInteraction } =
    useContext(AppContext);

  const runtimeMinutes = Number(movieDetails.Runtime?.match(/\d+/)?.[0] || 100);
  const durationSeconds = runtimeMinutes * 60;
  const positionSeconds = Math.round((progress / 100) * durationSeconds);

  // Fetch OMDB movie details
  useEffect(() => {
    setIsLoading(true);
    axios
      .get(`${API_ENDPOINT}i=${id}`)
      .then((res) => setMovieDetails(res.data))
      .finally(() => setIsLoading(false));
  }, [id]);

  // Fetch similar movies from backend vector search
  useEffect(() => {
    if (!id) return;
    setSimsLoading(true);
    setSimilarMovies([]);
    axios
      .get(`${BACKEND_URL}/items/${id}/similar`, { params: { limit: 12 } })
      .then((res) => {
        const items = (res.data?.items ?? []).map(({ item, score }) => ({
          imdbID: toOmdbId(item.imdbId),
          Poster: "N/A",
          Year: item.title?.match(/\((\d{4})\)/)?.[1] ?? "",
          Title: item.title,
          recScore: score,
        }));
        setSimilarMovies(items);
      })
      .catch(() => setSimilarMovies([]))
      .finally(() => setSimsLoading(false));
  }, [id]);

  useEffect(() => {
    const allMovies = [
      ...movies,
      ...hybridRecs,
      ...contentRecs,
      ...collabRecs,
      ...trendingRecs,
    ];
    const movie = allMovies.find((item) => item.imdbID === id);
    if (movie) setCurrentMovie(movie);
  }, [collabRecs, contentRecs, hybridRecs, id, movies, trendingRecs]);

  useEffect(() => {
    const loadBackendMovie = async () => {
      try {
        const response = await axios.get(`${BACKEND_URL}/search/movies/imdb/${id}`);
        setCurrentMovie((existing) => existing || normalizeRecItem({ item: response.data.item }));
      } catch {
        setCurrentMovie((existing) => existing || null);
      }
    };
    loadBackendMovie();
  }, [id]);

  useEffect(() => {
    if (!currentMovie?.movieId) return;
    const trackKey = `${id}:${currentMovie.movieId}`;
    if (trackedClickRef.current === trackKey) return;
    trackedClickRef.current = trackKey;
    trackInteraction({
      movieId: currentMovie.movieId,
      type: "click",
      source: "detail_page",
    });
  }, [currentMovie, id, trackInteraction]);

  useEffect(() => {
    if (!currentMovie?.movieId || !userId) return;
    setContextLoading(true);
    axios
      .get(`${BACKEND_URL}/recommend/${userId}`, {
        params: { limit: 10, context: currentMovie.movieId },
      })
      .then((response) => {
        setContextRecs((response.data?.items ?? []).map(normalizeRecItem));
      })
      .catch(() => setContextRecs([]))
      .finally(() => setContextLoading(false));
  }, [currentMovie, userId]);

  const loadInteractionSummary = async () => {
    if (!currentMovie?.movieId || !userId) return;
    setSummaryLoading(true);
    try {
      const response = await axios.get(
        `${BACKEND_URL}/interactions/${userId}/items/${currentMovie.movieId}/summary`
      );
      setInteractionSummary(response.data);
      if (response.data.latestRating) {
        setRatingValue(response.data.latestRating);
      }
      if (response.data.maxCompletionRate) {
        setProgress(Math.round(response.data.maxCompletionRate * 100));
      }
    } catch {
      setInteractionSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  };

  useEffect(() => {
    loadInteractionSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentMovie?.movieId, userId]);

  useEffect(() => {
    if (!isWatching) return undefined;

    const timer = window.setInterval(() => {
      setProgress((current) => {
        const next = Math.min(current + 1, 100);
        if (next >= 100) {
          window.clearInterval(timer);
          setIsWatching(false);
        }
        return next;
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isWatching]);

  const trackDetailAction = async (type, extra = {}) => {
    if (!currentMovie?.movieId) return;
    const result = await trackInteraction({
      movieId: currentMovie.movieId,
      type,
      source: "detail_page",
      positionSeconds,
      durationSeconds,
      clientEventId: `${Date.now()}-${type}-${currentMovie.movieId}`,
      metadata: {
        title: movieDetails.Title,
        imdbId: id,
        progressPercent: progress,
      },
      ...extra,
    });
    if (!result) {
      setActionStatus(`${type.replaceAll("_", " ")} failed`);
      return;
    }
    window.setTimeout(loadInteractionSummary, 1200);
    setActionStatus(
      type === "watch_progress"
        ? `Progress queued: ${Math.round((extra.completionRate || 0) * 100)}%`
        : `${type.replaceAll("_", " ")} queued`
    );
  };

  const handleWatchStart = () => {
    setIsWatching(true);
    trackDetailAction("watch_start", {
      completionRate: progress / 100,
    });
  };

  const handleWatchProgress = () => {
    trackDetailAction("watch_progress", {
      completionRate: progress / 100,
    });
  };

  const handleWatchComplete = () => {
    setIsWatching(false);
    setProgress(100);
    trackDetailAction("watch_complete", {
      completionRate: 1,
      positionSeconds: durationSeconds,
      metadata: {
        title: movieDetails.Title,
        imdbId: id,
        progressPercent: 100,
      },
    });
  };

  if (isLoading) {
    return <Loading />;
  }

  const {
    Poster,
    Title,
    imdbRating,
    Runtime,
    Year,
    Plot,
    Genre,
    Actors,
    Director,
    Production,
    Country,
  } = movieDetails;
  const displayPoster =
    Poster && Poster !== "N/A" ? Poster : currentMovie?.Poster || currentMovie?.poster;
  const hasPoster = displayPoster && displayPoster !== "N/A";

  return (
    <main className="MoviePage">
      <section className="Movie">
        <div className="movie-poster">
          {hasPoster ? (
            <img src={displayPoster} alt={Title} />
          ) : (
            <div className="detail-poster-fallback">
              <strong>{Title?.slice(0, 2) || "ML"}</strong>
              <span>MovieLens</span>
            </div>
          )}
        </div>
        <div className="movie-text">
          <h1>{Title}</h1>
          <p className="rating">
            {imdbRating} IMDB • {Runtime} • {Year}
            {currentMovie?.movieId ? ` • MovieLens #${currentMovie.movieId}` : ""}
          </p>
          <p className="plot">{Plot}</p>
          {currentMovie?.movieId && (
            <div className="detail-console">
              <div className="interaction-snapshot">
                <div>
                  <span>Your rating</span>
                  <strong>
                    {summaryLoading
                      ? "..."
                      : interactionSummary?.latestRating
                        ? `${interactionSummary.latestRating} stars`
                        : "Not rated"}
                  </strong>
                </div>
                <div>
                  <span>Progress</span>
                  <strong>
                    {summaryLoading
                      ? "..."
                      : `${Math.round((interactionSummary?.maxCompletionRate || 0) * 100)}%`}
                  </strong>
                </div>
                <div>
                  <span>Status</span>
                  <strong>
                    {interactionSummary?.watchCompleted
                      ? "Completed"
                      : interactionSummary?.watchStarted
                        ? "Started"
                        : "Not watched"}
                  </strong>
                </div>
                <div>
                  <span>Shares</span>
                  <strong>{interactionSummary?.shareCount || 0}</strong>
                </div>
              </div>
              <div className="control-block">
                <label htmlFor="progress">Watch progress</label>
                <div className="progress-control">
                  <input
                    id="progress"
                    type="range"
                    min="0"
                    max="100"
                    step="5"
                    value={progress}
                    onChange={(event) => setProgress(Number(event.target.value))}
                  />
                  <strong>{progress}%</strong>
                </div>
                <p className="progress-copy">
                  {isWatching ? "Watching session running" : "Use Start to simulate playback"}
                  {" • "}
                  {Math.round(positionSeconds / 60)} / {runtimeMinutes} min
                </p>
                <div className="movie-actions">
                  <button type="button" onClick={handleWatchStart}>
                    {isWatching ? "Watching" : "Start"}
                  </button>
                  <button type="button" onClick={handleWatchProgress}>
                    Log Progress
                  </button>
                  <button type="button" onClick={handleWatchComplete}>
                    Complete
                  </button>
                </div>
              </div>

              <div className="control-block">
                <label>Your rating</label>
                <div className="rating-control" aria-label="Rate this movie">
                  <div className="rating-picker">
                    {[1, 2, 3, 4, 5].map((value) => (
                      <button
                        type="button"
                        className={value <= ratingValue ? "star-button active" : "star-button"}
                        onClick={() => setRatingValue(value)}
                        aria-label={`${value} stars`}
                        key={value}
                      >
                        ★
                      </button>
                    ))}
                  </div>
                  <span className="rating-value">{ratingValue} / 5</span>
                  <button
                    className="rate-submit"
                    type="button"
                    onClick={() => trackDetailAction("rate", { score: ratingValue })}
                  >
                    Rate {ratingValue}★
                  </button>
                </div>
                <div className="movie-actions secondary-actions">
                  <button type="button" onClick={() => trackDetailAction("watchlist_remove")}>
                    Remove Watchlist
                  </button>
                  <button type="button" onClick={() => trackDetailAction("share")}>
                    Share
                  </button>
                </div>
              </div>
              {actionStatus && <p className="action-status">{actionStatus}</p>}
            </div>
          )}
          <p>
            <span>Genres: </span>
            {Genre}
          </p>
          <p>
            <span>Actors: </span>
            {Actors}
          </p>
          <p>
            <span>Director: </span>
            {Director}
          </p>
          <p>
            <span>Production: </span>
            {Production}
          </p>
          <p>
            <span>Countries: </span>
            {Country}
          </p>
        </div>
      </section>

      {currentMovie?.movieId && (
        <section className="ContextRecommendations">
          <div className="section-heading">
            <h2>Recommended With This Movie</h2>
            <span>Context: {Title}</span>
          </div>
          {contextLoading ? (
            <div className="rec-row skeleton-row">
              {Array.from({ length: 5 }).map((_, index) => (
                <div className="movie-skeleton" key={index} />
              ))}
            </div>
          ) : contextRecs.length ? (
            <div className="rec-row">
              {contextRecs.map((movie) => (
                <Movies
                  key={`context-${movie.movieId ?? movie.imdbID ?? movie.Title}`}
                  movie={{ ...movie, recSource: "context" }}
                />
              ))}
            </div>
          ) : (
            <div className="inline-alert">No context recommendations returned.</div>
          )}
        </section>
      )}
    </main>
  );
};

export default Movie;
