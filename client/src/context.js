import React, { createContext, useEffect, useState } from "react";
import axios from "axios";

export const API_ENDPOINT = `${process.env.REACT_APP_API_URL}?apikey=${process.env.REACT_APP_OMDB_API_KEY}&`;

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8080";

// MovieLens stores imdbId as a bare number (e.g. "114709").
// OMDB expects the "tt"-prefixed 7-digit format ("tt0114709").
const toOmdbId = (id) => (id ? `tt${String(id).padStart(7, "0")}` : null);

const normalizeRecItem = ({ item, score }) => ({
  imdbID: toOmdbId(item.imdbId),
  Poster: "N/A",
  Year: item.title?.match(/\((\d{4})\)/)?.[1] ?? "",
  Title: item.title,
  genres: item.genres ?? [],
  recScore: score,
});

export const AppContext = createContext();

export const AppProvider = ({ children }) => {
  const [searchMovie, setSearchMovie] = useState("avengers");
  const [userId, setUserId] = useState(
    process.env.REACT_APP_DEFAULT_USER_ID || "1"
  );

  const [movies, setMovies] = useState([]);
  const [hybridRecs, setHybridRecs] = useState([]);
  const [contentRecs, setContentRecs] = useState([]);
  const [collabRecs, setCollabRecs] = useState([]);
  const [trendingRecs, setTrendingRecs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [recsLoading, setRecsLoading] = useState(false);

  // ── Hybrid search: backend RRF ranking + OMDB poster enrichment ──────────
  useEffect(() => {
    const search = async () => {
      setIsLoading(true);
      try {
        const [backendRes, omdbRes] = await Promise.allSettled([
          axios.get(`${BACKEND_URL}/search/movies`, {
            params: { q: searchMovie, limit: 10, mode: "hybrid" },
          }),
          axios.get(`${API_ENDPOINT}s=${searchMovie}`),
        ]);

        // Build OMDB lookup by lowercase title → {Poster, Year, imdbID}
        const omdbByTitle = {};
        if (omdbRes.status === "fulfilled" && omdbRes.value.data?.Search) {
          omdbRes.value.data.Search.forEach((m) => {
            omdbByTitle[m.Title.toLowerCase()] = m;
          });
        }

        if (backendRes.status === "fulfilled" && backendRes.value.data?.items?.length) {
          const merged = backendRes.value.data.items.map(
            ({ item, rrfScore, textScore, vectorScore }) => {
              const omdb = omdbByTitle[item.title.toLowerCase()];
              return {
                imdbID: omdb?.imdbID ?? toOmdbId(item.imdbId),
                Poster: omdb?.Poster ?? "N/A",
                Year: omdb?.Year ?? item.title.match(/\((\d{4})\)/)?.[1] ?? "",
                Title: item.title,
                genres: item.genres ?? [],
                rrfScore,
                textScore,
                vectorScore,
              };
            }
          );
          setMovies(merged);
        } else if (omdbRes.status === "fulfilled" && omdbRes.value.data?.Search) {
          setMovies(omdbRes.value.data.Search);
        } else {
          setMovies([]);
        }
      } catch (err) {
        console.error(err);
        setMovies([]);
      } finally {
        setIsLoading(false);
      }
    };
    search();
  }, [searchMovie]);

  // ── All 3 recommendation types, fetched in parallel when userId changes ──
  useEffect(() => {
    if (!userId) return;
    setRecsLoading(true);

    const fetchRecs = async (path) => {
      try {
        const res = await axios.get(`${BACKEND_URL}/recommend/${userId}${path}`, {
          params: { limit: 10 },
        });
        return (res.data?.items ?? []).map(normalizeRecItem);
      } catch {
        return [];
      }
    };

    Promise.all([
      fetchRecs(""),            // hybrid
      fetchRecs("/content"),    // content-based
      fetchRecs("/collab"),     // collaborative
      fetchRecs("/trending"),   // trending (velocity-based)
    ]).then(([hybrid, content, collab, trending]) => {
      setHybridRecs(hybrid);
      setContentRecs(content);
      setCollabRecs(collab);
      setTrendingRecs(trending);
      setRecsLoading(false);
    });
  }, [userId]);

  return (
    <AppContext.Provider
      value={{
        movies,
        setSearchMovie,
        isLoading,
        userId,
        setUserId,
        hybridRecs,
        contentRecs,
        collabRecs,
        trendingRecs,
        recsLoading,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

