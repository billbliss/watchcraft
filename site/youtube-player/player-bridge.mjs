export const youtubeOrigin = "https://www.youtube-nocookie.com";
const allowedCommands = new Set([
  "mute",
  "pauseVideo",
  "playVideo",
  "seekTo",
  "setVolume",
  "stopVideo",
  "unMute",
]);

export function isValidVideoId(videoId) {
  return /^[A-Za-z0-9_-]{6,64}$/.test(videoId);
}

export function isAllowedPlayerCommand(message) {
  return (
    message?.event === "command" &&
    typeof message.func === "string" &&
    allowedCommands.has(message.func)
  );
}

export function youtubePlayerUrl(videoId, bridgeOrigin) {
  const embedParameters = new URLSearchParams({
    enablejsapi: "1",
    origin: bridgeOrigin,
    playsinline: "1",
    rel: "0",
    widget_referrer: bridgeOrigin,
  });
  return `${youtubeOrigin}/embed/${encodeURIComponent(videoId)}?${embedParameters}`;
}

export function youtubePlayerFrameUrl(videoId, bridgeUrl) {
  const url = new URL("./player-frame.html", bridgeUrl);
  url.searchParams.set("video", videoId);
  return url.toString();
}

export function startBridge() {
  const parameters = new URLSearchParams(window.location.search);
  const videoId = parameters.get("video") ?? "";

  if (!isValidVideoId(videoId)) {
    const error = document.createElement("div");
    error.className = "error";
    error.textContent = "This Watchcraft video link is invalid.";
    document.body.append(error);
    return;
  }

  const player = document.createElement("iframe");
  player.allow =
    "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
  player.allowFullscreen = true;
  player.referrerPolicy = "strict-origin-when-cross-origin";
  // WebKitGTK can omit Referer when a custom-protocol app creates a remote
  // iframe directly. Stage the player through a same-origin HTTPS document so
  // its navigation to YouTube carries Watchcraft's web origin on Linux too.
  player.src = youtubePlayerFrameUrl(videoId, window.location.href);
  player.title = "YouTube video player";
  document.body.append(player);

  window.addEventListener("message", (event) => {
    if (event.source === window.parent) {
      let message = event.data;
      if (typeof message === "string") {
        try {
          message = JSON.parse(message);
        } catch {
          return;
        }
      }
      if (isAllowedPlayerCommand(message)) {
        player.contentWindow?.postMessage(JSON.stringify(message), youtubeOrigin);
      }
      return;
    }

    if (event.source === player.contentWindow && event.origin === youtubeOrigin) {
      window.parent.postMessage(event.data, "*");
    }
  });
}

if (
  typeof window !== "undefined"
  && typeof document !== "undefined"
  && document.documentElement.hasAttribute("data-youtube-player-bridge")
) {
  startBridge();
}
