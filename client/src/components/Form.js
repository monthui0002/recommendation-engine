import React, { useContext, useEffect, useRef, useState } from "react";
import { AppContext } from "../context";
import SearchIcon from "@material-ui/icons/Search";
import "../styles/Form.css";
import { useHistory } from "react-router-dom";

const Form = ({ variant = "compact", autoFocus = false }) => {
  const { searchMovie, setSearchMovie } = useContext(AppContext);
  const inputRef = useRef();
  const history = useHistory();
  const [value, setValue] = useState(searchMovie);

  useEffect(() => {
    setValue(searchMovie);
  }, [searchMovie]);

  const handleSubmit = (e) => {
    e.preventDefault();
    setSearchMovie(value);
    if (value.trim()) history.push("/search");
  };

  const searchItems = (event) => {
    setValue(event.target.value);
    if (variant === "large") {
      setSearchMovie(event.target.value);
    }
  };

  return (
    <form className={`SearchForm SearchForm--${variant}`} onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Search movies, genres, tags..."
        value={value}
        ref={inputRef}
        onChange={searchItems}
        autoFocus={autoFocus}
      />
      <button type="submit">
        <SearchIcon />
      </button>
    </form>
  );
};

export default Form;
