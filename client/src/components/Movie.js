import React, { useContext, useEffect, useState } from "react";
import axios from "axios";
import Loading from "./Loading";
import Movies from "./Movies";
import { useParams } from "react-router-dom";
import "../styles/Movie.css";
import errorImage from "../errorImage.png";
import { API_ENDPOINT, BACKEND_URL, AppContext, logInteraction } from "../context";
import StarIcon from "@material-ui/icons/Star";
import StarBorderIcon from "@material-ui/icons/StarBorder";
import FavoriteIcon from "@material-ui/icons/Favorite";
import FavoriteBorderIcon from "@material-ui/icons/FavoriteBorder";

const toOmdbId = (id) => (id ? `tt${String(id).padStart(7, "0")}` : null);

const Movie = () => {
  const { userId } = useContext(AppContext);
  const [movieDetails, setMovieDetails] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [similarMovies, setSimilarMovies] = useState([]);
  const [simsLoading, setSimsLoading] = useState(false);
  const [watchlisted, setWatchlisted] = useState(false);
  const [userRating, setUserRating] = useState(0);   // 0 = not rated
  const [hoverRating, setHoverRating] = useState(0);
  const { id } = useParams();

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

  return (
    <>
      <div className="Movie">
        <div className="movie-poster">
          <img
            src={Poster === "N/A" ? errorImage : Poster}
            alt={Title}
            className={Poster === "N/A" ? "error-img" : null}
          />
        </div>
        <div className="movie-text">
          <h1>{Title}</h1>
          <div className="movie-actions">
            <p className="rating">
              <StarIcon style={{ fontSize: "0.9rem", verticalAlign: "middle", marginBottom: 1 }} />
              {imdbRating} &nbsp;·&nbsp; {Runtime} &nbsp;·&nbsp; {Year}
            </p>
            <button
              className={`watchlist-btn${watchlisted ? " active" : ""}`}
              onClick={() => {
                const next = !watchlisted;
                setWatchlisted(next);
                logInteraction(userId, id, next ? "watchlist_add" : "watchlist_remove");
              }}
              title={watchlisted ? "Remove from watchlist" : "Add to watchlist"}
            >
              {watchlisted ? <FavoriteIcon /> : <FavoriteBorderIcon />}
              {watchlisted ? "Saved" : "Watchlist"}
            </button>
            <div
              className="star-rating"
              onMouseLeave={() => setHoverRating(0)}
              title={userRating ? `Your rating: ${userRating}/5` : "Rate this movie"}
            >
              {[1, 2, 3, 4, 5].map((star) => {
                const filled = star <= (hoverRating || userRating);
                return (
                  <span
                    key={star}
                    className={`star${filled ? " filled" : ""}${star <= hoverRating ? " hover" : ""}`}
                    onMouseEnter={() => setHoverRating(star)}
                    onClick={() => {
                      setUserRating(star);
                      setHoverRating(0);
                      logInteraction(userId, id, "rate", {}, star);
                    }}
                  >
                    {filled ? <StarIcon /> : <StarBorderIcon />}
                  </span>
                );
              })}
              {userRating > 0 && (
                <span className="rating-label">{userRating}/5</span>
              )}
            </div>
          </div>
          <p className="plot">{Plot}</p>
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
      </div>

      {/* Similar Movies — vector search on the item's embedding */}
      {!simsLoading && similarMovies.length > 0 && (
        <div className="similar-section">
          <div className="RecSection">
            <h2 className="rec-title" style={{ borderLeftColor: "#7b5ea7" }}>
              Similar Movies
            </h2>
            <div className="rec-row">
              {similarMovies.map((movie) => (
                <Movies key={movie.imdbID ?? movie.Title} movie={movie} />
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default Movie;
