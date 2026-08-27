import {
  isValidVideoId,
  youtubePlayerUrl,
} from "./player-bridge.mjs";

const parameters = new URLSearchParams(window.location.search);
const videoId = parameters.get("video") ?? "";

if (!isValidVideoId(videoId)) {
  document.body.textContent = "This Watchcraft video link is invalid.";
} else {
  window.location.replace(youtubePlayerUrl(videoId, window.location.origin));
}
