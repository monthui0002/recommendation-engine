import React, { useContext } from "react";
import { Link } from "react-router-dom";
import { AppContext } from "../context";
import Movies from "./Movies";

const SkeletonRow = () => (
  <div className="rec-row skeleton-row">
    {Array.from({ length: 5 }).map((_, index) => (
      <div className="movie-skeleton" key={index} />
    ))}
  </div>
);

const RecRow = ({ title, subtitle, accent, items, loading, failed, emptyText }) => {
  const count = items?.length ?? 0;
  return (
    <div className="RecSection">
      <div className="section-heading" style={{ borderLeftColor: accent }}>
        <h2>{title}</h2>
        <span>{subtitle} • {count} items</span>
      </div>
      {loading ? (
        <SkeletonRow />
      ) : failed ? (
        <div className="inline-alert">{title} API unavailable.</div>
      ) : count > 0 ? (
        <div className="rec-row">
          {items.map((movie) => (
            <Movies key={`${title}-${movie.movieId ?? movie.imdbID ?? movie.Title}`} movie={movie} />
          ))}
        </div>
      ) : (
        <div className="inline-alert">{emptyText}</div>
      )}
    </div>
  );
};

const Home = React.memo(() => {
  const {
    recsLoading,
    recLoading,
    recsError,
    recFailures,
    metrics,
    userId,
    hybridRecs,
    contentRecs,
    collabRecs,
    trendingRecs,
  } = useContext(AppContext);

  return (
    <main className="dashboard">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">MovieLens user {userId}</p>
          <h1>Recommendation Workspace</h1>
        </div>
        <Link className="search-cta" to="/search">
          Search catalog
        </Link>
        <div className="metric-grid">
          <div className="metric-card">
            <span>Precision@K</span>
            <strong>{metrics?.precisionAtK ?? "--"}</strong>
          </div>
          <div className="metric-card">
            <span>Diversity</span>
            <strong>{metrics?.diversityScore ?? "--"}</strong>
          </div>
          <div className="metric-card">
            <span>Hybrid Items</span>
            <strong>{hybridRecs.length}</strong>
          </div>
          <div className="metric-card">
            <span>Collab Items</span>
            <strong>{collabRecs.length}</strong>
          </div>
        </div>
      </section>

      <RecRow
        title="For You"
        subtitle="Hybrid rank"
        accent="#3b82f6"
        items={hybridRecs}
        loading={recLoading.hybrid}
        failed={recFailures.hybrid}
        emptyText="No hybrid recommendations returned for this user."
      />
      <RecRow
        title="Similar To Your Taste"
        subtitle="Content profile"
        accent="#10b981"
        items={contentRecs}
        loading={recLoading.content}
        failed={recFailures.content}
        emptyText="No content-based candidates yet. Rate or watch a few movies to build the profile embedding."
      />
      <RecRow
        title="Users Also Liked"
        subtitle="Collaborative"
        accent="#f97316"
        items={collabRecs}
        loading={recLoading.collab}
        failed={recFailures.collab}
        emptyText="No collaborative neighbors yet. Add ratings, clicks, or watch events that overlap with other users."
      />
      <RecRow
        title="Trending Now"
        subtitle="Last 24 hours"
        accent="#eab308"
        items={trendingRecs}
        loading={recLoading.trending}
        failed={recFailures.trending}
        emptyText="No recent engagement events in the trending window."
      />

      {recsError && <div className="inline-alert">{recsError}</div>}

      {recsLoading && <div className="quiet-status">Refreshing recommendation rails...</div>}
    </main>
  );
});

export default Home;
