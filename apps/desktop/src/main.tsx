import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DesktopApp } from "./DesktopApp";
import "../../web/src/styles.css";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Watchcraft root element is missing");

createRoot(root).render(
  <StrictMode>
    <DesktopApp />
  </StrictMode>,
);
