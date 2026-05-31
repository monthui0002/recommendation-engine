import React, { createContext, useCallback, useEffect, useState } from "react";
import axios from "axios";

export const API_ENDPOINT = `${process.env.REACT_APP_API_URL}?apikey=${process.env.REACT_APP_OMDB_API_KEY}&`;

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8080";
const IMPRESSION_TTL_MS = 30 * 60 * 1000;

// MovieLens stores imdbId as a bare number (e.g. "114709").
// OMDB expects the "tt"-prefixed 7-digit format ("tt0114709").
const toOmdbId = (id) => (id ? `tt${String(id).padStart(7, "0")}` : null);

export const normalizeRecItem = ({ item, score, source, sources }) => ({
  imdbID: toOmdbId(item.imdbId),
  movieId: item.movieId,
  Poster: item.poster || item.Poster || "N/A",
  Year: item.title?.match(/\((\d{4})\)/)?.[1] ?? "",
  Title: item.title,
  genres: item.genres ?? [],
  avgRating: item.avgRating,
  ratingCount: item.ratingCount,
  recScore: score,
  recSource: source ?? sources?.join(", ") ?? "recommendation",
  isRecommendation: true,
});

export const AppContext = createContext();

const shouldSkipDuplicateImpression = ({ userId, movieId, source }) => {
  if (typeof window === "undefined" || !window.sessionStorage) return false;

  const key = `impression:${userId}:${movieId}:${source || "unknown"}`;
  const now = Date.now();
  const previous = Number(window.sessionStorage.getItem(key) || 0);
  if (previous && now - previous < IMPRESSION_TTL_MS) {
    return true;
  }
  window.sessionStorage.setItem(key, String(now));
  return false;
};

export const AppProvider = ({ children }) => {
  const [searchMovie, setSearchMovieState] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const [userId, setUserId] = useState(
    process.env.REACT_APP_DEFAULT_USER_ID || "1"
  );

  const [movies, setMovies] = useState([]);
  const [popularMovies, setPopularMovies] = useState([]);
  const [popularLoading, setPopularLoading] = useState(true);
  const [hybridRecs, setHybridRecs] = useState([]);
  const [contentRecs, setContentRecs] = useState([]);
  const [collabRecs, setCollabRecs] = useState([]);
  const [trendingRecs, setTrendingRecs] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [recsLoading, setRecsLoading] = useState(true);
  const [recLoading, setRecLoading] = useState({
    hybrid: true,
    content: true,
    collab: true,
    trending: true,
  });
  const [recsRefreshKey, setRecsRefreshKey] = useState(0);
  const [searchError, setSearchError] = useState("");
  const [recsError, setRecsError] = useState("");
  const [recFailures, setRecFailures] = useState({
    hybrid: false,
    content: false,
    collab: false,
    trending: false,
  });

  const setSearchMovie = useCallback((value) => {
    const nextValue = value.trim();
    setSearchMovieState(nextValue);
    setHasSearched(Boolean(nextValue));
    if (!nextValue) {
      setMovies([]);
      setSearchError("");
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    setPopularLoading(true);
    axios
      .get(`${BACKEND_URL}/search/movies/popular`, { params: { limit: 12 } })
      .then((res) => {
        setPopularMovies((res.data?.items ?? []).map(normalizeRecItem));
      })
      .catch(() => setPopularMovies([]))
      .finally(() => setPopularLoading(false));
  }, []);

  const trackInteraction = useCallback(
    async ({
      movieId,
      type,
      score = null,
      completionRate = null,
      source = null,
      ...extra
    }) => {
      if (!userId || !movieId || !type) return;
      if (
        type === "impression" &&
        shouldSkipDuplicateImpression({ userId, movieId, source })
      ) {
        return;
      }
      try {
        const response = await axios.post(`${BACKEND_URL}/interact/${type}`, {
          userId,
          itemId: movieId,
          score,
          completionRate,
          source,
          ...extra,
        });
        if (type !== "impression") {
          window.setTimeout(() => setRecsRefreshKey((key) => key + 1), 900);
          window.setTimeout(() => setRecsRefreshKey((key) => key + 1), 2500);
        }
        return response.data;
      } catch (err) {
        // Interaction tracking should never block browsing.
        console.debug("interaction tracking failed", err);
        return null;
      }
    },
    [userId]
  );

  // ── Hybrid search: backend RRF ranking + OMDB poster enrichment ──────────
  useEffect(() => {
    if (!searchMovie) {
      setMovies([]);
      setIsLoading(false);
      setSearchError("");
      return undefined;
    }

    const debounce = setTimeout(() => {
      const search = async () => {
        setIsLoading(true);
        setSearchError("");
        try {
          const backendRes = await axios.get(`${BACKEND_URL}/search/movies`, {
            params: { q: searchMovie, limit: 12, mode: "hybrid" },
          });

          if (backendRes.data?.items?.length) {
            const initial = backendRes.data.items.map(
              ({ item, rrfScore, textScore, vectorScore }) => ({
                imdbID: toOmdbId(item.imdbId),
                movieId: item.movieId,
                Poster: item.poster || "N/A",
                Year: item.title.match(/\((\d{4})\)/)?.[1] ?? "",
                Title: item.title,
                genres: item.genres ?? [],
                avgRating: item.avgRating,
                ratingCount: item.ratingCount,
                rrfScore,
                textScore,
                vectorScore,
                source: "search",
              })
            );
            setMovies(initial);
            setIsLoading(false);

            axios
              .get(`${API_ENDPOINT}s=${searchMovie}`)
              .then((omdbRes) => {
                const omdbByTitle = {};
                if (omdbRes.data?.Search) {
                  omdbRes.data.Search.forEach((m) => {
                    omdbByTitle[m.Title.toLowerCase()] = m;
                  });
                }
                setMovies((current) =>
                  current.map((movie) => {
                    const omdb = omdbByTitle[movie.Title.toLowerCase()];
                    return omdb
                      ? {
                          ...movie,
                          imdbID: omdb.imdbID ?? movie.imdbID,
                          Poster:
                            movie.Poster && movie.Poster !== "N/A"
                              ? movie.Poster
                              : omdb.Poster ?? movie.Poster,
                          Year: omdb.Year ?? movie.Year,
                        }
                      : movie;
                  })
                );
              })
              .catch(() => {});
          } else {
            const omdbRes = await axios.get(`${API_ENDPOINT}s=${searchMovie}`);
            setMovies(omdbRes.data?.Search ?? []);
          }
        } catch (err) {
          console.error(err);
          setSearchError("Search service unavailable");
          setMovies([]);
        } finally {
          setIsLoading(false);
        }
      };
      search();
    }, 280);

    return () => clearTimeout(debounce);
  }, [searchMovie]);

  // ── All 3 recommendation types, fetched in parallel when userId changes ──
  useEffect(() => {
    if (!userId) return;
    setRecsLoading(true);
    setRecsError("");
    setRecLoading({
      hybrid: true,
      content: true,
      collab: true,
      trending: true,
    });

    const fetchRecs = async (key, path) => {
      setRecFailures((failures) => ({ ...failures, [key]: false }));
      try {
        const res = await axios.get(`${BACKEND_URL}/recommend/${userId}${path}`, {
          params: { limit: 8 },
        });
        const items = (res.data?.items ?? []).map(normalizeRecItem);
        if (key === "hybrid") setHybridRecs(items);
        if (key === "content") setContentRecs(items);
        if (key === "collab") setCollabRecs(items);
        if (key === "trending") setTrendingRecs(items);
        return { key, items, failed: false };
      } catch {
        setRecFailures((failures) => ({ ...failures, [key]: true }));
        return { key, items: [], failed: true };
      } finally {
        setRecLoading((loading) => ({ ...loading, [key]: false }));
      }
    };

    Promise.all([
      fetchRecs("hybrid", ""),
      fetchRecs("content", "/content"),
      fetchRecs("collab", "/collab"),
      fetchRecs("trending", "/trending"),
      axios
        .get(`${BACKEND_URL}/metrics/${userId}`, { params: { k: 10 } })
        .then((res) => res.data)
        .catch(() => null),
    ])
      .then(([hybrid, content, collab, trending, metricsResult]) => {
        const recGroups = [hybrid, content, collab, trending];
        const allFailed = recGroups.every((group) => group.failed);
        const anyItems = recGroups.some((group) => group.items.length);
        setMetrics(metricsResult);
        if (allFailed) {
          setRecsError("Recommendation API unavailable");
        } else if (!anyItems) {
          setRecsError("No recommendations returned for this user");
        }
      })
      .finally(() => setRecsLoading(false));
  }, [userId, recsRefreshKey]);

  return (
    <AppContext.Provider
      value={{
        movies,
        popularMovies,
        popularLoading,
        searchMovie,
        hasSearched,
        setSearchMovie,
        isLoading,
        searchError,
        userId,
        setUserId,
        hybridRecs,
        contentRecs,
        collabRecs,
        trendingRecs,
        recsLoading,
        recLoading,
        recsError,
        recFailures,
        metrics,
        trackInteraction,
        refreshRecommendations: () => setRecsRefreshKey((key) => key + 1),
      }}
    >
      {children}
    </AppContext.Provider>
  );
};
