import React from "react";
import { useHistory } from "react-router-dom";
import "../styles/Movies.css";
import errorImage from "../errorImage.png";

const Movies = ({ movie }) => {
  const history = useHistory();
  const { imdbID, Poster, Title, Year } = movie;

  const handleClick = () => {
    if (imdbID) history.push(`/movies/${imdbID}`);
  };

  return (
    <div className="Movies" onClick={handleClick} style={!imdbID ? { cursor: "default" } : {}}>
      <img src={Poster === "N/A" ? errorImage : Poster} alt={Title} />
      <p>{Title}</p>
      <p>{Year}</p>
    </div>
  );
};

export default Movies;
