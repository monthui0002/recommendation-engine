import React, { useContext } from "react";
import { AppContext } from "../context";
import Loading from "./Loading";
import Movies from "./Movies";
import Error from "./Error";

const RecRow = ({ title, accent, items }) => {
  if (!items || items.length === 0) return null;
  return (
    <div className="RecSection">
      <h2 className="rec-title" style={{ borderLeftColor: accent }}>
        {title}
      </h2>
      <div className="rec-row">
        {items.map((movie) => (
          <Movies key={movie.imdbID ?? movie.Title} movie={movie} />
        ))}
      </div>
    </div>
  );
};

const Home = React.memo(() => {
  const { movies, isLoading, recsLoading, hybridRecs, contentRecs, collabRecs, trendingRecs } =
    useContext(AppContext);

  if (isLoading) {
    return <Loading />;
  }

  return (
    <>
      {/* Search Results */}
      <div className="Home">
        {movies && movies.length > 0
          ? movies.map((movie) => (
              <Movies key={movie.imdbID ?? movie.Title} movie={movie} />
            ))
          : <Error />}
      </div>

      {/* Recommendation rows — hidden while loading */}
      {!recsLoading && (
        <>
          <RecRow
            title="For You — Hybrid"
            accent="#3434bb"
            items={hybridRecs}
          />
          <RecRow
            title="Because You Watched — Content"
            accent="#1a8a5a"
            items={contentRecs}
          />
          <RecRow
            title="Others Also Liked — Collaborative"
            accent="#a83232"
            items={collabRecs}
          />
          <RecRow
            title="Trending Now — Last 24h"
            accent="#b87c00"
            items={trendingRecs}
          />
        </>
      )}
    </>
  );
});

export default Home;
