import React, { useContext } from "react";
import { useHistory } from "react-router-dom";
import "../styles/Movies.css";
import errorImage from "../errorImage.png";
import { AppContext, logInteraction } from "../context";

/**
 * recType — when set, this card is inside a recommendation row.
 *   Enables: rec_click tracking, dismiss button.
 * onDismiss(imdbID) — callback to remove the card from the row.
 * dismissType — interaction type logged on dismiss (default: "dismiss").
 */
const Movies = ({ movie, recType, onDismiss, dismissType = "dismiss" }) => {
  const history = useHistory();
  const { userId } = useContext(AppContext);
  const { imdbID, Poster, Title, Year } = movie;

  const handleClick = () => {
    if (recType && imdbID) {
      logInteraction(userId, imdbID, "rec_click", { recType });
    }
    if (imdbID) history.push(`/movies/${imdbID}`);
  };

  const handleDismiss = (e) => {
    e.stopPropagation();
    if (imdbID) logInteraction(userId, imdbID, dismissType, { recType });
    if (onDismiss) onDismiss(imdbID ?? Title);
  };

  return (
    <div
      className="Movies"
      onClick={handleClick}
      style={!imdbID ? { cursor: "default" } : {}}
    >
      {recType && (
        <button
          className="dismiss-btn"
          onClick={handleDismiss}
          title="Not interested"
          aria-label="Dismiss"
        >
          ✕
        </button>
      )}
      <div className="poster-wrap">
        <img src={Poster === "N/A" ? errorImage : Poster} alt={Title} />
      </div>
      <div className="movie-info">
        <p className="title">{Title}</p>
        <p className="year">{Year}</p>
      </div>
    </div>
  );
};

export default Movies;
