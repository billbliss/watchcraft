import test from "node:test";
import assert from "node:assert/strict";
import { parseYouTubeSource, submissionUrl } from "./youtubeRequest.ts";
test("canonicalizes video forms and removes tracking, timestamps and unrelated parameters", () => {
  for (const url of ["https://youtu.be/PjObX9XQvgI?si=personal", "https://m.youtube.com/watch?v=PjObX9XQvgI&t=12&email=private", "youtube.com/shorts/PjObX9XQvgI"]) {
    assert.equal(parseYouTubeSource(url).url, "https://www.youtube.com/watch?v=PjObX9XQvgI");
  }
});
test("keeps explicit playlist context and recognizes playlist IDs and channel handles", () => {
  const id = "PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab";
  assert.equal(parseYouTubeSource(id).kind, "playlist");
  assert.equal(parseYouTubeSource(`https://youtube.com/watch?v=PjObX9XQvgI&list=${id}&index=2`).playlistId, id);
  assert.equal(parseYouTubeSource("https://youtube.com/@3Blue1Brown/videos").url, "https://www.youtube.com/@3blue1brown");
});
test("rejects foreign hosts, credentials, arbitrary ports, and unsupported inputs", () => {
  for (const url of ["https://youtube.com.evil.test/watch?v=PjObX9XQvgI", "https://user@youtube.com/watch?v=PjObX9XQvgI", "https://youtube.com:123/watch?v=PjObX9XQvgI", "file:///etc/passwd", "https://youtube.com/playlist?list=RD1234567890", "https://youtube.com/watch?v=bad"]) assert.throws(() => parseYouTubeSource(url));
});
test("handoff puts only canonical content in the fragment, never in a query string", () => {
  const url = new URL(submissionUrl("https://youtu.be/PjObX9XQvgI?si=private"));
  assert.equal(url.pathname, "/submit/"); assert.equal(url.search, "");
  assert.equal(new URLSearchParams(url.hash.slice(1)).get("source"), "https://www.youtube.com/watch?v=PjObX9XQvgI");
});
