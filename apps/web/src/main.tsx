import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { repositoryFromLocation } from "./catalog/httpCatalogRepository";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Watchcraft root element is missing");

createRoot(root).render(
  <StrictMode>
    <App repository={repositoryFromLocation(window.location)} />
  </StrictMode>,
);
