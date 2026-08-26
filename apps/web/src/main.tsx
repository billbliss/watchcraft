import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { WebApp } from "./WebApp";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Watchcraft root element is missing");

createRoot(root).render(
  <StrictMode>
    <WebApp />
  </StrictMode>,
);
