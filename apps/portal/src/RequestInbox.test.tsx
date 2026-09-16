// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useAction, useMutation, useQuery } from "convex/react";
import { RequestInbox } from "./RequestInbox";
vi.mock("convex/react", () => ({ useAction: vi.fn(), useMutation: vi.fn(), useQuery: vi.fn() }));
const preview = vi.fn();
const review = Object.assign(vi.fn(), { withOptimisticUpdate: vi.fn() });
const item = { id: "request", revision: 2, title: "A requested channel", sourceUrl: "https://www.youtube.com/@CustomerBliss", options: [{ scope: "channel", title: "Entire channel", count: null }], selectedScope: "channel", state: "planning", submittedAt: 1000, requesters: [{ label: "Anonymous", scope: "channel" }], hasMoreRequesters: false, preparation: null };
beforeEach(() => { vi.mocked(useAction).mockReturnValue(preview); vi.mocked(useMutation).mockReturnValue(review); review.mockResolvedValue(undefined); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });
test("queued requests honestly wait for the authoring operator", () => {
  vi.mocked(useQuery).mockReturnValue({ requests: [item], hasMore: false });
  render(<RequestInbox />);
  expect(screen.getByText("Queued for planning")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Update scope" }) as HTMLButtonElement).disabled).toBe(true);
});
test("failed planning offers a retry bound to the request revision", async () => {
  vi.mocked(useQuery).mockReturnValue({ requests: [{ ...item, preparation: { stage: "failed", stalled: false } }], hasMore: false });
  render(<RequestInbox />);
  expect(screen.getByText("Planning needs attention")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry planning" }));
  await waitFor(() => expect(review).toHaveBeenCalledWith({ requestId: "request", expectedRevision: 2, selectedScope: "channel", decision: "plan" }));
});
test("active preparation displays its current stage", () => {
  vi.mocked(useQuery).mockReturnValue({ requests: [{ ...item, preparation: { stage: "estimating", stalled: false } }], hasMore: false });
  render(<RequestInbox />);
  expect(screen.getByText("Estimating time and cost")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
});

test("expansion loads the source preview once without repeating the row details", async () => {
  vi.mocked(useQuery).mockReturnValue({ requests: [{ ...item, state: "submitted" }], hasMore: false });
  preview.mockResolvedValue({ source: { kind: "channel" }, thumbnail: "https://yt3.ggpht.com/example", channel: "Channel", warning: null });
  render(<RequestInbox />);
  expect(screen.queryByText("New request")).toBeNull();
  expect(preview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: `Expand ${item.title}` }));
  await screen.findByText("YouTube channel");
  expect(preview).toHaveBeenCalledWith({ source: item.sourceUrl });
  expect(screen.queryByText(/Requested scopes:/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: `Collapse ${item.title}` }));
  fireEvent.click(screen.getByRole("button", { name: `Expand ${item.title}` }));
  expect(preview).toHaveBeenCalledTimes(1);
});
