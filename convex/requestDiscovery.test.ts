import { afterEach, expect, test, vi } from "vitest";
import { discover, playlistPreview } from "./requestDiscovery";
const playlistId = "PLBsP89CPrMeMV1oP42Zn2DrWpnFoSaufA";
const cover = `https://i9.ytimg.com/s_p/${playlistId}/landscape_mqdefault.jpg`;
const page = {
  playlistMetadataRenderer: { title: "Retro Tech" },
  pageHeaderViewModel: {
    heroImage: { contentPreviewImageViewModel: { image: { sources: [{ url: cover, width: 320 }, { url: cover.replace("mqdefault", "maxresdefault"), width: 2560 }] } } },
    metadata: { contentMetadataViewModel: { metadataRows: [
      { metadataParts: [{ avatarStack: { avatarStackViewModel: { text: { content: "by Marques Brownlee" } } } }] },
      { metadataParts: [{ text: { content: "Playlist" } }, { text: { content: "6 videos" } }, { text: { content: "1,128,866 views" } }] },
    ] } },
  },
};
afterEach(() => vi.unstubAllGlobals());
test("playlist artwork, owner and video count come from the current header", () => {
  expect(playlistPreview(page)).toEqual({ title: "Retro Tech", owner: "Marques Brownlee", count: 6, thumbnail: cover });
});
test.each([playlistId, `https://www.youtube.com/playlist?list=${playlistId}`])("ID and URL input both get a playlist preview: %s", async input => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(`var ytInitialData = ${JSON.stringify(page)};`)));
  const result = await discover(input);
  expect(result).toMatchObject({ title: "Retro Tech", channel: "Marques Brownlee", thumbnail: cover, options: [{ scope: "playlist", count: 6 }] });
});
test("older sidebar artwork is supported without mistaking views for videos", () => {
  expect(playlistPreview({
    playlistSidebarPrimaryInfoRenderer: { title: { simpleText: "A playlist" }, stats: [{ simpleText: "9,000 views" }], thumbnailRenderer: { playlistVideoThumbnailRenderer: { thumbnail: { thumbnails: [{ url: cover, width: 320 }] } } } },
    playlistSidebarSecondaryInfoRenderer: { videoOwner: { videoOwnerRenderer: { title: { runs: [{ text: "Playlist owner" }] } } } },
  })).toEqual({ title: "A playlist", owner: "Playlist owner", count: null, thumbnail: cover });
});
test("missing metadata stays unknown and untrusted artwork is not used", () => {
  expect(playlistPreview(null)).toEqual({ title: "", owner: null, count: null, thumbnail: null });
  expect(playlistPreview({ pageHeaderViewModel: { heroImage: { contentPreviewImageViewModel: { image: { sources: [{ url: "https://example.com/tracker" }] } } } } }).thumbnail).toBeNull();
});

test.each(["@CustomerBliss", "https://www.youtube.com/@CustomerBliss", "UCrCA2ot8FTazPNIGcnefYEA", "https://www.youtube.com/channel/UCrCA2ot8FTazPNIGcnefYEA"])("channel inputs get their profile image: %s", async input => {
  const avatar = "https://yt3.googleusercontent.com/ytc/channel-avatar=s160";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(`var ytInitialData = ${JSON.stringify({ channelMetadataRenderer: { title: "Jeanne Bliss (CustomerBliss)", externalId: "UCrCA2ot8FTazPNIGcnefYEA", avatar: { thumbnails: [{ url: avatar, width: 160 }] } } })};`)));
  expect(await discover(input)).toMatchObject({ title: "Jeanne Bliss (CustomerBliss)", thumbnail: avatar, source: { kind: "channel" } });
});
