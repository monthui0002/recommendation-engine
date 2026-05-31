import React, { useContext, useState } from "react";
import { AppContext } from "../context";
import Loading from "./Loading";
import Movies from "./Movies";
import Error from "./Error";

const RecRow = ({ title, accent, items, recType }) => {
  const [dismissed, setDismissed] = useState(new Set());

  const visible = items
    ? items.filter((m) => !dismissed.has(m.imdbID ?? m.Title))
    : [];

  if (visible.length === 0) return null;

  const handleDismiss = (key) =>
    setDismissed((prev) => new Set([...prev, key]));

  return (
    <div className="RecSection">
      <h2 className="rec-title" style={{ borderLeftColor: accent }}>
        {title}
      </h2>
      <div className="rec-row">
        {visible.map((movie) => (
          <Movies
            key={movie.imdbID ?? movie.Title}
            movie={movie}
            recType={recType}
            onDismiss={handleDismiss}
          />
        ))}
      </div>
    </div>
  );
};

const Home = React.memo(() => {
  const {
    movies,
    isLoading,
    recsLoading,
    hybridRecs,
    contentRecs,
    collabRecs,
    trendingRecs,
  } = useContext(AppContext);

  if (isLoading) {
    return <Loading />;
  }

  const hasRecs =
    hybridRecs.length > 0 ||
    contentRecs.length > 0 ||
    collabRecs.length > 0 ||
    trendingRecs.length > 0;

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

      {/* Recommendation section divider */}
      {!recsLoading && hasRecs && (
        <p className="section-label">Recommendations for You</p>
      )}

      {/* Recommendation rows */}
      {!recsLoading && (
        <>
          <RecRow title="For You — Hybrid"           accent="#3434bb" items={hybridRecs}   recType="hybrid"      />
          <RecRow title="Based on What You Watched"   accent="#1a8a5a" items={contentRecs}  recType="content"     />
          <RecRow title="Others Also Liked"           accent="#a83232" items={collabRecs}   recType="collab"      />
          <RecRow title="Trending Now — Last 24h"     accent="#b87c00" items={trendingRecs} recType="trending"    />
        </>
      )}
    </>
  );
});

export default Home;

