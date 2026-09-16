import { parseYouTubeSource, type YouTubeSource, type RequestScope } from "../packages/catalog-core/src/youtubeRequest";
export interface ScopeOption { scope: RequestScope; title: string; targetUrl: string; count: number | null; }
export interface Discovery { source: YouTubeSource; title: string; channel: string | null; thumbnail: string | null; options: ScopeOption[]; warning: string | null; }
type Json = Record<string, any>;
// This mirrors the existing source-only discovery in authoring/youtube_discovery.py.
export function embeddedJson(page: string, name: string): Json | null {
  const start = new RegExp(`(?:var\\s+${name}|window\\["${name}"\\])\\s*=\\s*`).exec(page);
  if (!start) return null;
  let depth = 0, quoted = false, escaped = false;
  const offset = start.index + start[0].length;
  for (let i = offset; i < page.length; i++) {
    const ch = page[i];
    if (quoted) { if (escaped) escaped = false; else if (ch === "\\") escaped = true; else if (ch === '"') quoted = false; }
    else if (ch === '"') quoted = true;
    else if (ch === "{" || ch === "[") depth++;
    else if (ch === "}" || ch === "]") { if (--depth === 0) { try { return JSON.parse(page.slice(offset, i + 1)); } catch { return null; } } }
  }
  return null;
}
export function nested(value: unknown, key: string): Json[] {
  if (!value || typeof value !== "object") return [];
  const object = value as Json;
  return [...(object[key] && typeof object[key] === "object" ? [object[key]] : []), ...Object.values(object).flatMap(child => nested(child, key))];
}
function titleText(value: any): string { return typeof value === "string" ? value : value?.simpleText ?? value?.content ?? value?.runs?.map((r: any) => r.text ?? "").join("") ?? ""; }
function thumbnailUrl(sources: unknown): string | null {
  if (!Array.isArray(sources)) return null;
  const candidates = sources.filter((image): image is { url: string; width?: number } => {
    try {
      const url = new URL(image.url);
      return url.protocol === "https:" && !url.username && !url.password && !url.port
        && (url.hostname === "ytimg.com" || url.hostname.endsWith(".ytimg.com")
          || url.hostname === "yt3.ggpht.com" || url.hostname === "yt3.googleusercontent.com");
    } catch { return false; }
  }).sort((a, b) => (a.width ?? 0) - (b.width ?? 0));
  return (candidates.find(image => (image.width ?? 0) >= 320) ?? candidates.at(-1))?.url ?? null;
}
export function playlistPreview(data: unknown) {
  const metadata = nested(data, "playlistMetadataRenderer")[0];
  const header = nested(data, "playlistHeaderRenderer")[0];
  const page = nested(data, "pageHeaderViewModel")[0];
  const sidebar = nested(data, "playlistSidebarPrimaryInfoRenderer")[0];
  const secondary = nested(data, "playlistSidebarSecondaryInfoRenderer")[0];
  const rows = page?.metadata?.contentMetadataViewModel?.metadataRows ?? [];
  const parts = rows.flatMap((row: Json) => row.metadataParts ?? []);
  const countText = [titleText(header?.numVideosText), ...parts.map((part: Json) => titleText(part.text)), ...(sidebar?.stats ?? []).map(titleText)]
    .find(text => /^\s*[\d,]+\s+videos?\s*$/i.test(text));
  const legacyCount = titleText(header?.numVideosText);
  const count = countText ? Number(countText.replace(/[^0-9]/g, "")) : /^\d+$/.test(legacyCount) ? Number(legacyCount) : null;
  const owner = titleText(secondary?.videoOwner?.videoOwnerRenderer?.title)
    || titleText(header?.ownerText)
    || titleText(parts.find((part: Json) => part.avatarStack?.avatarStackViewModel?.text)?.avatarStack.avatarStackViewModel.text).replace(/^by\s+/i, "");
  return {
    title: (titleText(metadata?.title) || titleText(page?.title?.dynamicTextViewModel?.text) || titleText(header?.title) || titleText(sidebar?.title)).slice(0, 300),
    owner: owner.slice(0, 200) || null,
    count: count !== null && Number.isSafeInteger(count) ? count : null,
    thumbnail: thumbnailUrl(page?.heroImage?.contentPreviewImageViewModel?.image?.sources)
      ?? thumbnailUrl(nested(header?.playlistHeaderBanner, "playlistVideoThumbnailRenderer")[0]?.thumbnail?.thumbnails)
      ?? thumbnailUrl(sidebar?.thumbnailRenderer?.playlistVideoThumbnailRenderer?.thumbnail?.thumbnails)
      ?? thumbnailUrl(nested(data, "playlistVideoRenderer")[0]?.thumbnail?.thumbnails),
  };
}
export function channelPreview(data: unknown) {
  const metadata = nested(data, "channelMetadataRenderer")[0];
  const page = nested(data, "pageHeaderViewModel")[0];
  const legacy = nested(data, "c4TabbedHeaderRenderer")[0];
  return {
    title: (titleText(metadata?.title) || titleText(page?.title?.dynamicTextViewModel?.text) || titleText(legacy?.title)).slice(0, 300),
    thumbnail: thumbnailUrl(page?.image?.decoratedAvatarViewModel?.avatar?.avatarViewModel?.image?.sources)
      ?? thumbnailUrl(metadata?.avatar?.thumbnails) ?? thumbnailUrl(legacy?.avatar?.thumbnails),
  };
}
async function read(url: string, payload?: Json): Promise<string> {
  const target = new URL(url);
  if (target.origin !== "https://www.youtube.com") throw new Error("Invalid discovery host");
  const response = await fetch(target, { redirect: "error", signal: AbortSignal.timeout(12000),
    ...(payload ? { method: "POST", body: JSON.stringify(payload) } : {}),
    headers: { "User-Agent": "Mozilla/5.0 (compatible; WatchcraftAuthor/0.1)", "Accept-Language": "en", ...(payload ? { "Content-Type": "application/json" } : {}) } });
  if (!response.ok || !response.body) throw new Error("YouTube unavailable");
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let size = 0, text = "";
  try { while (true) { const chunk = await reader.read(); if (chunk.done) break; size += chunk.value.byteLength; if (size > 4_000_000) throw new Error("Response too large"); text += decoder.decode(chunk.value, { stream: true }); } }
  finally { await reader.cancel(); }
  return text + decoder.decode();
}
export async function discover(input: string): Promise<Discovery> {
  const source = parseYouTubeSource(input);
  const result: Discovery = { source, title: source.videoId ? `YouTube video ${source.videoId}` : source.playlistId ? `YouTube playlist ${source.playlistId}` : source.channelPath!, channel: null, thumbnail: null, options: [], warning: null };
  let channelUrl = source.kind === "channel" ? source.url : null;
  if (source.videoId) {
    result.options.push({ scope: "video", title: "Just this video", targetUrl: `https://www.youtube.com/watch?v=${source.videoId}`, count: 1 });
    try {
      const data = JSON.parse(await read(`https://www.youtube.com/oembed?url=${encodeURIComponent(`https://www.youtube.com/watch?v=${source.videoId}`)}&format=json`));
      result.title = String(data.title).slice(0, 300); result.channel = String(data.author_name ?? "").slice(0, 200);
      try { channelUrl = parseYouTubeSource(data.author_url).url; } catch { /* Channel choices stay unavailable without a trusted channel. */ }
      result.thumbnail = `https://i.ytimg.com/vi/${source.videoId}/mqdefault.jpg`;
    } catch { result.warning = "YouTube couldn't provide details right now. You can still submit this link for review."; }
  }
  if (source.playlistId) {
    const option: ScopeOption = { scope: "playlist", title: "This playlist", targetUrl: `https://www.youtube.com/playlist?list=${source.playlistId}`, count: null };
    result.options.push(option);
    try {
      const data = embeddedJson(await read(`${option.targetUrl}&hl=en`), "ytInitialData");
      const preview = playlistPreview(data);
      option.count = preview.count;
      if (source.kind === "playlist") {
        if (preview.title) result.title = preview.title;
        result.channel = preview.owner;
        result.thumbnail = preview.thumbnail;
      }
    } catch { result.warning ??= "Playlist details will be checked before processing."; }
  }
  if (channelUrl) {
    try {
      const page = await read(`${channelUrl}/videos?view=0&sort=p&flow=grid&hl=en`);
      let data = embeddedJson(page, "ytInitialData");
      const metadata = nested(data, "channelMetadataRenderer")[0];
      const preview = channelPreview(data);
      if (preview.title) result.channel = preview.title.slice(0, 200);
      if (source.kind === "channel") {
        if (preview.title) result.title = preview.title;
        result.thumbnail = preview.thumbnail;
      }
      const id = metadata?.externalId;
      if (typeof id === "string" && /^UC[A-Za-z0-9_-]{22}$/.test(id)) channelUrl = `https://www.youtube.com/channel/${id}`;
      // A ignored sort parameter must never turn a Latest list into "Popular".
      let popularSelected = nested(data, "chipCloudChipRenderer").some(chip => chip.isSelected === true && /^popular$/i.test(titleText(chip.text)))
        || nested(data, "chipViewModel").some(chip => chip.selected === true && /^popular$/i.test(titleText(chip.text)))
        || nested(data, "sortFilterSubMenuRenderer").some(menu => menu.subMenuItems?.some((item: any) => item.selected === true && /popular/i.test(titleText(item.title))));
      if (!popularSelected) {
        // Current public channel pages expose sorting as a continuation command.
        const chip = nested(data, "chipViewModel").find(item => /^popular$/i.test(titleText(item.text)));
        const continuation = chip?.tapCommand?.innertubeCommand?.continuationCommand?.token;
        const version = /"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"\\]{1,100})"/.exec(page)?.[1];
        if (typeof continuation === "string" && continuation.length < 5000 && version) {
          data = JSON.parse(await read("https://www.youtube.com/youtubei/v1/browse", { context: { client: { clientName: "WEB", clientVersion: version, hl: "en" } }, continuation }));
          popularSelected = true;
        }
      }
      const videoIds: string[] = popularSelected ? [
        ...nested(data, "videoRenderer").map(v => v.videoId),
        ...nested(data, "lockupViewModel").filter(v => v.contentType === "LOCKUP_CONTENT_TYPE_VIDEO").map(v => v.contentId),
      ].filter((id): id is string => typeof id === "string" && /^[A-Za-z0-9_-]{11}$/.test(id)) : [];
      const ids = [...new Set(videoIds)].slice(0, 20);
      if (ids.length && (!source.videoId || ids.includes(source.videoId))) result.options.push({ scope: "popular", title: "Popular videos from this channel", targetUrl: channelUrl, count: ids.length });
    } catch { /* Popular membership cannot be inferred without observing it. */ }
    result.options.push({ scope: "channel", title: "The entire channel", targetUrl: channelUrl, count: null });
  }
  return result;
}

export interface ExistingCollection { title: string; manifestUrl: string; supportsWeb: boolean; }
async function collectionJson(url: string): Promise<any> {
  const parsed = new URL(url);
  const allowed = parsed.origin === "https://collections.watchcraft.stream"
    || (parsed.origin === "https://raw.githubusercontent.com" && parsed.pathname.startsWith("/billbliss/watchcraft-collections/"));
  if (!allowed || parsed.username || parsed.password) throw new Error("Unsupported collection host");
  const response = await fetch(parsed, { signal: AbortSignal.timeout(6000), redirect: "error" });
  if (!response.ok || !response.body) throw new Error("Collection unavailable");
  const reader = response.body.getReader(); let size = 0, result = ""; const decoder = new TextDecoder();
  try { while (true) { const chunk = await reader.read(); if (chunk.done) break; size += chunk.value.byteLength; if (size > 4_000_000) throw new Error("Collection too large"); result += decoder.decode(chunk.value, { stream: true }); } }
  finally { await reader.cancel(); }
  return JSON.parse(result + decoder.decode());
}
export async function existingCollections(source: YouTubeSource): Promise<ExistingCollection[]> {
  if (!source.videoId && !source.playlistId) return [];
  try {
    const directory = await collectionJson("https://collections.watchcraft.stream/directory.json");
    const candidates = (Array.isArray(directory.collections) ? directory.collections : []).filter((c: any) => c.archived !== true && typeof c.manifest_url === "string").slice(0, 50);
    const matches: ExistingCollection[] = [];
    for (let offset = 0; offset < candidates.length; offset += 5) {
      await Promise.all(candidates.slice(offset, offset + 5).map(async (candidate: any) => {
        try {
          const manifest = await collectionJson(candidate.manifest_url);
          if (manifest.kind !== "watchcraft.collection") return;
          const includesVideo = source.videoId && Object.values(manifest.items ?? {}).some((item: any) => Array.isArray(item.media) && item.media.some((media: any) => media.type === "youtube" && media.video_id === source.videoId));
          const includesPlaylist = !source.videoId && source.playlistId && (manifest.source?.playlist_id === source.playlistId || manifest.source?.canonical_url === source.url);
          if (includesVideo || includesPlaylist) matches.push({ title: String(manifest.title).slice(0,300), manifestUrl: candidate.manifest_url, supportsWeb: Array.isArray(candidate.media_modes) && candidate.media_modes.includes("remote") });
        } catch { /* A failed collection lookup must not prevent a new suggestion. */ }
      }));
    }
    return matches;
  } catch { return []; }
}
