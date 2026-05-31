import React, { useContext } from "react";
import { AppContext } from "../context";
import Form from "./Form";
import Movies from "./Movies";
import Error from "./Error";

const SearchPage = () => {
  const { movies, searchMovie, hasSearched, isLoading, searchError } =
    useContext(AppContext);
  const { popularMovies, popularLoading } = useContext(AppContext);
  const showingPopular = !hasSearched;

  return (
    <main className="SearchPage">
      <section className="search-panel">
        <p className="eyebrow">Movie catalog</p>
        <h1>Search movies</h1>
        <Form variant="large" autoFocus />
      </section>

      <section className="SearchSection search-results-panel">
        <div className="section-heading search-heading">
          <h2>Results</h2>
          <span>{searchMovie ? `Query: ${searchMovie}` : "Popular movies"}</span>
        </div>

        {(showingPopular ? popularLoading : isLoading) ? (
          <div className="Home">
            {Array.from({ length: 8 }).map((_, index) => (
              <div className="movie-skeleton" key={index} />
            ))}
          </div>
        ) : !showingPopular && searchError ? (
          <div className="inline-alert">{searchError}</div>
        ) : showingPopular && popularMovies.length > 0 ? (
          <div className="Home">
            {popularMovies.map((movie) => (
              <Movies key={`popular-search-${movie.movieId ?? movie.imdbID ?? movie.Title}`} movie={movie} />
            ))}
          </div>
        ) : hasSearched && movies.length > 0 ? (
          <div className="Home">
            {movies.map((movie) => (
              <Movies key={`search-${movie.movieId ?? movie.imdbID ?? movie.Title}`} movie={movie} />
            ))}
          </div>
        ) : hasSearched ? (
          <Error />
        ) : (
          <div className="inline-alert">Popular movies unavailable.</div>
        )}
      </section>
    </main>
  );
};

export default SearchPage;
