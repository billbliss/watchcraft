/** Normalize content identifiers only. Never persist pasted tracking parameters. */
export type RequestScope = "video" | "playlist" | "popular" | "channel";
export interface YouTubeSource {
  kind: "video" | "playlist" | "channel";
  url: string;
  key: string;
  videoId?: string;
  playlistId?: string;
  channelPath?: string;
}
const videoId = /^[A-Za-z0-9_-]{11}$/;
const playlistId = /^(?:PL|UU|LL|FL|OLAK5uy_)[A-Za-z0-9_-]{8,95}$/;
export function parseYouTubeSource(input: string): YouTubeSource {
  let value = input.trim();
  if (!value || value.length > 2048) throw new Error("Paste a YouTube video, playlist, or channel link.");
  if (/^UC[A-Za-z0-9_-]{22}$/.test(value)) value = `https://www.youtube.com/channel/${value}`;
  else if (/^@[\p{L}\p{N}_.-]{1,100}$/u.test(value)) value = `https://www.youtube.com/${value}`;
  else if (playlistId.test(value)) value = `https://www.youtube.com/playlist?list=${value}`;
  else if (videoId.test(value)) value = `https://www.youtube.com/watch?v=${value}`;
  else if (/^(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\//i.test(value)) value = `https://${value}`;
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("That isn't a recognizable YouTube link or playlist ID."); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.port
    || !["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"].includes(url.hostname.toLowerCase())) {
    throw new Error("Use a link from youtube.com or youtu.be.");
  }
  const parts = url.pathname.split("/").filter(Boolean);
  const video = url.hostname.endsWith("youtu.be") ? parts[0] : parts[0] === "watch" ? url.searchParams.get("v") : ["shorts", "live", "embed"].includes(parts[0]) ? parts[1] : null;
  const playlist = url.searchParams.get("list");
  if (video && videoId.test(video)) {
    const list = playlist && playlistId.test(playlist) ? playlist : undefined;
    return { kind: "video", videoId: video, ...(list ? { playlistId: list } : {}), url: `https://www.youtube.com/watch?v=${video}${list ? `&list=${list}` : ""}`, key: `video:${video}${list ? `:playlist:${list}` : ""}` };
  }
  if (parts[0] === "playlist" && playlist && playlistId.test(playlist)) return { kind: "playlist", playlistId: playlist, url: `https://www.youtube.com/playlist?list=${playlist}`, key: `playlist:${playlist}` };
  const path = parts[0]?.startsWith("@") && /^@[\p{L}\p{N}_.-]{1,100}$/u.test(decodeURIComponent(parts[0])) ? decodeURIComponent(parts[0]).toLowerCase()
    : parts[0] === "channel" && /^UC[A-Za-z0-9_-]{22}$/.test(parts[1] ?? "") ? `channel/${parts[1]}` : null;
  if (path && (parts.length === (path.startsWith("channel/") ? 2 : 1) || ["videos", "shorts", "streams", "featured", "playlists"].includes(parts.at(-1)!))) {
    return { kind: "channel", channelPath: path, url: `https://www.youtube.com/${path}`, key: path.startsWith("@") ? `handle:${path}` : path };
  }
  throw new Error("Use a video, a saved playlist, or a channel link. YouTube mixes aren't supported.");
}
export function isYouTubeSource(value: string): boolean {
  try { parseYouTubeSource(value); return true; } catch { return false; }
}
export function submissionUrl(value?: string, base = "https://watchcraft.stream/submit/"): string {
  const url = new URL(base);
  // The fragment keeps pasted content out of page URLs sent to the web host.
  if (value) url.hash = new URLSearchParams({ source: parseYouTubeSource(value).url }).toString();
  return url.href;
}
