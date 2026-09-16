// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useAction, useQuery } from "convex/react";
import { SubmissionApp } from "./SubmissionApp";
vi.hoisted(() => { vi.stubEnv("VITE_CONVEX_URL", "https://test.convex.cloud"); });
vi.mock("convex/react", () => ({
  ConvexProvider: ({ children }: { children: unknown }) => children,
  ConvexReactClient: class {}, useAction: vi.fn(), useQuery: vi.fn(),
}));
const preview = vi.fn(); const submit = vi.fn();
beforeEach(() => {
  window.history.replaceState(null, "", "/submit/");
  // Convex function references expose their names via a global symbol.
  vi.mocked(useAction).mockImplementation((ref: any) => ref[Symbol.for("functionName")]?.endsWith(":submit") ? submit : preview);
  vi.mocked(useQuery).mockReturnValue(undefined);
  preview.mockResolvedValue({ source: { key: "video:PjObX9XQvgI", kind: "video", url: "https://www.youtube.com/watch?v=PjObX9XQvgI" }, title: "Example video", channel: "Example channel", thumbnail: null, warning: null, existing: [], options: [{ scope: "video", title: "Just this video", count: 1, targetUrl: "https://www.youtube.com/watch?v=PjObX9XQvgI" }] });
  submit.mockResolvedValue({ requestId: "request", duplicate: false });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });
test("anonymous visitors can inspect and submit without invoking account UI", async () => {
  render(<SubmissionApp />);
  fireEvent.change(screen.getByLabelText("YouTube video, playlist, or channel"), { target: { value: "https://youtu.be/PjObX9XQvgI" } });
  fireEvent.click(screen.getByRole("button", { name: "Check link" }));
  await screen.findByText("Example video");
  fireEvent.click(screen.getByRole("button", { name: "Submit without signing in" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0]).toMatchObject({ preferredScope: "video", attachAccount: false, token: expect.stringMatching(/^[a-f0-9]{64}$/) });
  await waitFor(() => expect(window.location.hash).toMatch(/^#status=[a-f0-9]{64}$/));
  expect(window.location.search).toBe("");
});
test("a failed submission keeps its status token when retried", async () => {
  submit.mockRejectedValueOnce(new Error("network"));
  render(<SubmissionApp />);
  fireEvent.change(screen.getByLabelText("YouTube video, playlist, or channel"), { target: { value: "https://youtu.be/PjObX9XQvgI" } });
  fireEvent.click(screen.getByRole("button", { name: "Check link" }));
  const button = await screen.findByRole("button", { name: "Submit without signing in" });
  fireEvent.click(button); await screen.findByRole("alert"); fireEvent.click(button);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
  expect(submit.mock.calls[0][0].token).toBe(submit.mock.calls[1][0].token);
});
test("status links show progress without exposing submitter identity", async () => {
  window.history.replaceState(null, "", `/submit/#status=${"a".repeat(64)}`);
  vi.mocked(useQuery).mockReturnValue({ title: "Example request", state: "planning", processingState: null, selectedScope: "video", preferredScope: "video", sourceUrl: "https://youtu.be/PjObX9XQvgI" });
  render(<SubmissionApp />);
  expect(screen.getByText("Preparing a plan and estimate")).toBeTruthy();
  expect(screen.getByText(/Anyone with the link/)).toBeTruthy();
});

test("a source passed from Settings automatically loads its preview without submitting", async () => {
  window.history.replaceState(null, "", "/submit/#source=https%3A%2F%2Fyoutu.be%2FPjObX9XQvgI");
  render(<SubmissionApp />);
  await screen.findByText("Example video");
  expect(preview).toHaveBeenCalledExactlyOnceWith({ source: "https://youtu.be/PjObX9XQvgI" });
  expect(submit).not.toHaveBeenCalled();
});
test("a failed automatic preview can be retried manually", async () => {
  window.history.replaceState(null, "", "/submit/#source=https%3A%2F%2Fyoutu.be%2FPjObX9XQvgI");
  preview.mockRejectedValueOnce(new Error("network"));
  render(<SubmissionApp />);
  await screen.findByRole("alert");
  expect(preview).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Check link" }));
  await screen.findByText("Example video");
  expect(preview).toHaveBeenCalledTimes(2);
  expect(submit).not.toHaveBeenCalled();
});
