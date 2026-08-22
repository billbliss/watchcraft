import assert from "node:assert/strict";
import test from "node:test";
import {
  clockSeconds,
  displayClock,
  inferTimelineClockMode,
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
