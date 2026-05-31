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
          <h1>MovieLens Recommender</h1>
        </Link>
        <div className="navbar-right">
          <Form />
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
          {location.pathname !== "/" && (
            <Link to="/" className="go-home">
              <KeyboardBackspaceIcon /> Home
            </Link>
          )}
        </div>
      </div>
    </div>
  );
};

export default Navbar;
