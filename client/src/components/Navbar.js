import React, { useContext } from "react";
import Form from "./Form";
import { Link, useLocation } from "react-router-dom";
import "../styles/Navbar.css";
import KeyboardBackspaceIcon from "@material-ui/icons/KeyboardBackspace";
import BookmarkBorderIcon from "@material-ui/icons/BookmarkBorder";
import BookmarkIcon from "@material-ui/icons/Bookmark";
import { AppContext } from "../context";

const Navbar = () => {
  const location = useLocation();
  const { userId, setUserId } = useContext(AppContext);

  return (
    <div className="Navbar">
      <div className="container">
        <Link to="/">
          <h1>Movie App</h1>
        </Link>
        <div className="navbar-right">
          {location.pathname === "/" && <Form />}
          {location.pathname !== "/" && (
            <Link to="/" className="go-home">
              <KeyboardBackspaceIcon /> Home
            </Link>
          )}
          <Link
            to="/watchlist"
            className={`watchlist-nav-btn${location.pathname === "/watchlist" ? " active" : ""}`}
            title="My Watchlist"
          >
            {location.pathname === "/watchlist" ? <BookmarkIcon /> : <BookmarkBorderIcon />}
            Watchlist
          </Link>
          <div className="user-selector">
            <label htmlFor="userId">User</label>
            <input
              id="userId"
              type="number"
              min="1"
              max="610"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Navbar;
