import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DesktopApp } from "./DesktopApp";
import { PlaybackSmokeTest } from "./PlaybackSmokeTest";
import "../../web/src/styles.css";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Watchcraft root element is missing");
const playbackSmoke = new URLSearchParams(window.location.search).has("playbackSmoke");

createRoot(root).render(
  playbackSmoke
    ? <PlaybackSmokeTest />
    : (
        <StrictMode>
          <DesktopApp />
        </StrictMode>
      ),
);
