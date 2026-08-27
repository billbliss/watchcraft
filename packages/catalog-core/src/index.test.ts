import assert from "node:assert/strict";
import test from "node:test";
import {
  clockSeconds,
  displayClock,
  inferTimelineClockMode,
  topicPassesFrequencyFilter,
  youtubeBridgeUrl,
  youtubeEmbedUrl,
  type AnalysisSection,
} from "./index.ts";

function section(start: string, end: string): AnalysisSection {
  return { start, end, title: "Chapter", concepts: [], description: "Test" };
}

test("detects minute-second timelines stored in three clock fields", () => {
  const sections = [
    section("00:00:00", "23:22:00"),
    section("23:22:00", "46:28:00"),
  ];
  const mode = inferTimelineClockMode(sections, 2793.2);

  assert.equal(mode, "minutes-seconds-fraction");
  assert.equal(clockSeconds("23:22:00", mode), 1402);
  assert.equal(displayClock("23:22:00", mode), "23:22");
});

test("creates a privacy-enhanced controllable YouTube embed URL", () => {
  assert.equal(
    youtubeEmbedUrl("PjObX9XQvgI", "https://watchcraft.example"),
    "https://www.youtube-nocookie.com/embed/PjObX9XQvgI?enablejsapi=1&playsinline=1&rel=0&origin=https%3A%2F%2Fwatchcraft.example&widget_referrer=https%3A%2F%2Fwatchcraft.example",
  );
});

test("creates a Watchcraft HTTPS bridge URL for desktop YouTube playback", () => {
  assert.equal(
    youtubeBridgeUrl("PjObX9XQvgI"),
    "https://watchcraft.stream/youtube-player/?video=PjObX9XQvgI",
  );
});

test("shows topics in small collections where frequency is not meaningful", () => {
  assert.equal(topicPassesFrequencyFilter(1, 1, 40), true);
  assert.equal(topicPassesFrequencyFilter(1, 4, 40), true);
  assert.equal(topicPassesFrequencyFilter(4, 4, 40), true);
  assert.equal(topicPassesFrequencyFilter(1, 5, 40), false);
  assert.equal(topicPassesFrequencyFilter(2, 5, 40), true);
});

test("keeps valid hour-minute-second timelines", () => {
  const sections = [
    section("00:00:00.000", "00:23:22.000"),
    section("00:23:22.000", "00:46:28.000"),
  ];
  const mode = inferTimelineClockMode(sections, 2793.2);

  assert.equal(mode, "hours-minutes-seconds");
  assert.equal(displayClock("00:23:22.000", mode), "23:22");
  assert.equal(displayClock("01:02:03", mode), "1:02:03");
});
