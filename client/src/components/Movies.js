import React, { useContext, useEffect, useRef, useState } from "react";
import { useHistory } from "react-router-dom";
import "../styles/Movies.css";
import { AppContext } from "../context";

/**
 * recType — when set, this card is inside a recommendation row.
 *   Enables: rec_click tracking, dismiss button.
 * onDismiss(imdbID) — callback to remove the card from the row.
 * dismissType — interaction type logged on dismiss (default: "dismiss").
 */
const Movies = ({ movie, recType, onDismiss, dismissType = "dismiss" }) => {
  const history = useHistory();
  const cardRef = useRef(null);
  const viewedRef = useRef(null);
  const [hidden, setHidden] = useState(false);
  const { trackInteraction } = useContext(AppContext);
  const {
    imdbID,
    movieId,
    Poster,
    Title,
    Year,
    genres,
    avgRating,
    ratingCount,
    recScore,
    isRecommendation,
    recSource,
  } = movie;
  const eventSource = isRecommendation ? recSource || "recommendation" : "search";
  const hasPoster = Poster && Poster !== "N/A";
  const posterInitials = (Title || "Movie")
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();

  useEffect(() => {
    const viewKey = `${movieId}:${eventSource}`;
    if (!movieId || viewedRef.current === viewKey) return;

    const node = cardRef.current;
    if (!node || !("IntersectionObserver" in window)) {
      viewedRef.current = viewKey;
      trackInteraction({ movieId, type: "impression", source: eventSource });
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || entry.intersectionRatio < 0.55) return;
        viewedRef.current = viewKey;
        trackInteraction({ movieId, type: "impression", source: eventSource });
        observer.disconnect();
      },
      { threshold: [0.55] }
    );
    observer.observe(node);

    return () => observer.disconnect();
  }, [eventSource, movieId, trackInteraction]);

  const handleClick = () => {
    if (movieId) {
      trackInteraction({
        movieId,
        type: isRecommendation ? "click" : "search_click",
        source: eventSource,
      });
    }
    if (imdbID) history.push(`/movies/${imdbID}`);
  };

  const trackButton = (event, type) => {
    event.stopPropagation();
    if (!movieId) return;
    trackInteraction({
      movieId,
      type,
      source: eventSource,
    });
    if (type === "hide") setHidden(true);
  };

  if (hidden) return null;

  return (
    <article
      className="Movies"
      onClick={handleClick}
      ref={cardRef}
      style={!imdbID ? { cursor: "default" } : {}}
    >
      <div className="poster-wrap">
        {hasPoster ? (
          <img src={Poster} alt={Title} loading="lazy" />
        ) : (
          <div className="poster-fallback" aria-label={`${Title} poster placeholder`}>
            <span>{posterInitials}</span>
            <small>MovieLens</small>
          </div>
        )}
        {avgRating && <span className="rating-badge">{Number(avgRating).toFixed(1)}</span>}
        {movieId && (
          <div className="quick-actions" aria-label="Movie actions">
            <button type="button" onClick={(e) => trackButton(e, "watchlist_add")} title="Add to watchlist">
              +
            </button>
            <button type="button" onClick={(e) => trackButton(e, "like")} title="Like">
              ♥
            </button>
            <button type="button" onClick={(e) => trackButton(e, "dislike")} title="Dislike">
              −
            </button>
            <button type="button" onClick={(e) => trackButton(e, "hide")} title="Hide">
              ×
            </button>
          </div>
        )}
      </div>
      <div className="movie-copy">
        <p className="movie-title">{Title}</p>
        <div className="movie-subline">
          <span>{Year || "Movie"}</span>
          {ratingCount ? <span>{Number(ratingCount).toLocaleString()} ratings</span> : null}
        </div>
        {genres?.length ? (
          <div className="genre-strip">
            {genres.slice(0, 2).map((genre) => (
              <span key={genre}>{genre}</span>
            ))}
          </div>
        ) : null}
        <div className="score-footer">
          <span>{isRecommendation ? recSource : "search"}</span>
          {recScore !== undefined && recScore !== null ? (
            <strong>{Number(recScore).toFixed(3)}</strong>
          ) : null}
        </div>
      </div>
    </article>
  );
};

export default Movies;
