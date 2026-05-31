import React, { useContext, useEffect, useState } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { AppContext, BACKEND_URL } from "../context";
import Movies from "./Movies";
import Loading from "./Loading";
import "../styles/Watchlist.css";

const toOmdbId = (id) => (id ? `tt${String(id).padStart(7, "0")}` : null);

const Watchlist = () => {
  const { userId } = useContext(AppContext);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [removed, setRemoved] = useState(new Set());

  const handleRemove = (key) => setRemoved((prev) => new Set([...prev, key]));

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    axios
      .get(`${BACKEND_URL}/items/watchlist/${userId}`)
      .then((res) => setItems(res.data?.items ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [userId]);

  if (loading) return <Loading />;

  const visible = items.filter((item) => !removed.has(item._id ?? item.imdbId));

  return (
    <div className="Watchlist">
      <div className="watchlist-header">
        <h1>My Watchlist</h1>
        <span className="watchlist-count">{visible.length} movies</span>
      </div>

      {visible.length === 0 ? (
        <div className="watchlist-empty">
          <p>Your watchlist is empty.</p>
          <Link to="/" className="browse-link">Browse recommendations →</Link>
        </div>
      ) : (
        <div className="watchlist-grid">
          {visible.map((item) => {
            const movie = {
              imdbID: toOmdbId(item.imdbId),
              Poster: "N/A",
              Title: item.title,
              Year: item.title?.match(/\((\d{4})\)/)?.[1] ?? "",
            };
            return (
              <Movies
                key={item._id ?? item.imdbId}
                movie={movie}
                recType="watchlist"
                dismissType="watchlist_remove"
                onDismiss={handleRemove}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};

export default Watchlist;
