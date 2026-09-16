// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useMutation, useQuery } from "convex/react";
import { ReviewQueue, duration, cost } from "./ReviewQueue";
vi.mock("./RequestInbox", () => ({ RequestInbox: () => null }));
vi.mock("convex/react", () => ({ useQuery: vi.fn(), useMutation: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const submission = {
  id: "execution", title: "Linear algebra", submittedAt: 1000, submittedBy: "Bill", projectRevision: 2,
  revision: 1, approvalSha256: "digest", total: 2, completed: 0, updatedAt: 2000, concurrency: 1,
  selectedItems: [{ id: "youtube:PjObX9XQvgI", url: "https://www.youtube.com/watch?v=PjObX9XQvgI" }],
  estimate: { expectedSeconds: 120, highSeconds: 300, expectedCostUsd: .25, highCostUsd: .5,
    confidence: "low", fullPlanItems: 3, concurrency: 2, caveats: ["Duration-based estimate"] },
};
function setup(mutate = vi.fn().mockResolvedValue({})) {
  vi.mocked(useQuery).mockReturnValue({ pending: [submission], accepted: [], running: [], activeJobs: [], completed: [{ ...submission, id: "done", title: "Finished project", completed: 2 }] });
  vi.mocked(useMutation).mockReturnValue(mutate as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  return mutate;
}
test("review cards show attribution, estimate scope, and honest unavailable completion controls", () => {
  setup();
  expect(screen.getByText("Bill")).toBeTruthy();
  expect(screen.getByText("2 min")).toBeTruthy();
  expect(screen.getByText("$0.25")).toBeTruthy();
  expect(screen.getByText(/Estimates cover all 3/)).toBeTruthy();
  expect(screen.getByRole("heading", { name: "In-flight processing" })).toBeTruthy();
  fireEvent.click(screen.getByText("Completed projects"));
  expect((screen.getByRole("button", { name: "Load in Watchcraft" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Submit pull request" }) as HTMLButtonElement).disabled).toBe(true);
});
test.each(["Accept", "Reject"])("%s binds the displayed revision and estimate to the review", async label => {
  const mutate = setup();
  fireEvent.click(screen.getByRole("button", { name: `${label} Linear algebra` }));
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  expect(mutate.mock.calls[0][0]).toMatchObject({ executionId: "execution", expectedRevision: 1, approvalSha256: "digest", decision: label.toLowerCase(), commandId: expect.any(String) });
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain(label === "Accept" ? "accepted" : "rejected"));
});
test("an uncertain request can be retried without recording a second decision", async () => {
  const mutate = setup(vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({}));
  fireEvent.click(screen.getByRole("button", { name: "Accept Linear algebra" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Accept Linear algebra" }));
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
  expect(mutate.mock.calls[0][0].commandId).toBe(mutate.mock.calls[1][0].commandId);
  await screen.findByRole("status");
});
test("unknown estimates are distinguishable from free or very small work", () => {
  expect(cost(null)).toBe("Not estimated");
  expect(cost(0)).toBe("$0.00");
  expect(cost(.001)).toBe("Less than $0.01");
  expect(duration(null)).toBe("Not estimated");
  expect(duration(3601)).toBe("1 hr 1 min");
});

test("verified previews enable loading and PR creation only on click", async () => {
  const mutate = vi.fn().mockResolvedValue({});
  const preview = "https://raw.githubusercontent.com/billbliss/watchcraft-collections/abc/collections/example/collection.json";
  vi.mocked(useQuery).mockReturnValue({ pending: [], accepted: [], running: [], activeJobs: [], completed: [{ ...submission, workflow: { phase: "ready", state: "ready", preview_url: preview } }] });
  vi.mocked(useMutation).mockReturnValue(mutate as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  fireEvent.click(screen.getByText("Completed projects"));
  expect(mutate).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Load in Watchcraft" }).getAttribute("href")).toBe(`watchcraft://install?url=${encodeURIComponent(preview)}`);
  fireEvent.click(screen.getByRole("button", { name: "Submit pull request" }));
  await waitFor(() => expect(mutate).toHaveBeenCalledExactlyOnceWith({ executionId: "execution" }));
});

test("assembly stays visible in flight and exposes failed-stage retry", () => {
  vi.mocked(useQuery).mockImplementation((_query, args?: unknown) => args ? { completed: 2, total: 2, failures: [], historyLimited: false } : { pending: [], accepted: [], running: [], activeJobs: [], completed: [{ ...submission, workflow: { phase: "compilation", state: "failed" } }] });
  vi.mocked(useMutation).mockReturnValue(vi.fn() as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  expect(screen.getByRole("button", { name: "Retry building collection" })).toBeTruthy();
  expect(screen.getByText("Needs attention · Building collection")).toBeTruthy();
});

test("failure history can be expanded, collapsed, and reopened", () => {
  vi.mocked(useQuery).mockImplementation((_query, args?: unknown) => args ? {
    completed: 1, total: 2, historyLimited: false,
    failures: [{ id: "video", title: "Failed video", attempts: 2, failureCount: 1, errors: [{ occurred_at: 1000, message: "Download failed" }] }],
  } : { pending: [], accepted: [], running: [], activeJobs: [], completed: [], failed: [{ ...submission, workflow: { phase: "processing", state: "failed" } }] });
  vi.mocked(useMutation).mockReturnValue(vi.fn() as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  expect(screen.queryByText("Failed video")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Show failures/ }));
  expect(screen.getByText("Failed video")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Hide failures/ }));
  expect(screen.queryByText("Failed video")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Show failures/ }));
  expect(screen.getByText("Failed video")).toBeTruthy();
});

test("a retried failed execution appears in flight with its queue position and blocker", () => {
  vi.mocked(useQuery).mockReturnValue({ pending: [], accepted: [], activeJobs: [], completed: [],
    running: [{ ...submission, id: "active", title: "Jeanne Bliss", state: "running", workflow: { phase: "processing", state: "running" } }],
    failed: [{ ...submission, title: "GDC", state: "failed", completed: 18, total: 20, queuePosition: 1, waitingOn: "Jeanne Bliss", workflow: { phase: "processing", state: "queued" } }],
  });
  vi.mocked(useMutation).mockReturnValue(vi.fn() as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  expect(screen.getByText("GDC")).toBeTruthy();
  expect(screen.getByText("18 / 20 videos processed")).toBeTruthy();
  expect(screen.getByText(/Queued · #1 waiting.*Waiting for Jeanne Bliss/)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Needs attention" })).toBeNull();
});

test("stage failure explains why repeating the same job will not help", () => {
  vi.mocked(useQuery).mockImplementation((_query, args?: unknown) => args ? {
    completed: 104, total: 104, historyLimited: false, failures: [], stageFailure: {
      message: "sections must be a list", affectedVideo: "Short customer video", occurredAt: 1000,
      attempts: 1, jobId: "job-123", logUrl: "https://github.com/billbliss/watchcraft/actions/runs/123",
      guidance: "This job cannot be retried unchanged.",
    },
  } : { pending: [], accepted: [], running: [], activeJobs: [], failed: [], completed: [{ ...submission, workflow: { phase: "normalization", state: "failed" } }] });
  vi.mocked(useMutation).mockReturnValue(vi.fn() as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  expect(screen.getByText("Short customer video")).toBeTruthy();
  expect(screen.getByText("This job cannot be retried unchanged.")).toBeTruthy();
  fireEvent.click(screen.getByText("Diagnostics"));
  expect(screen.getByRole("link", { name: /Open worker log/ }).getAttribute("href")).toContain("/runs/123");
});


test("finished videos do not imply collection preparation is complete", () => {
  vi.mocked(useQuery).mockReturnValue({ pending: [], accepted: [], running: [], activeJobs: [], failed: [],
    completed: [{ ...submission, completed: 104, total: 104, workflow: { phase: "normalization", state: "running" } }],
  });
  vi.mocked(useMutation).mockReturnValue(vi.fn() as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  expect(screen.getByText("All 104 videos processed")).toBeTruthy();
  expect(screen.getByText("Organizing topics · In progress")).toBeTruthy();
  expect(screen.getByText("Collection preparation is still underway.")).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
});


test("collections awaiting a PR are visible outside completed history", () => {
  vi.mocked(useQuery).mockReturnValue({ pending: [], accepted: [], running: [], activeJobs: [], failed: [], completed: [
    { ...submission, id: "ready", title: "Ready collection", workflow: { phase: "ready", state: "ready", preview_url: "https://example.com/collection.json" } },
    { ...submission, id: "submitted", title: "Submitted collection", workflow: { phase: "ready", state: "ready", preview_url: "https://example.com/collection.json", pull_request_url: "https://github.com/billbliss/watchcraft-collections/pull/42" } },
    { ...submission, id: "historical", title: "Historical collection" },
  ] });
  vi.mocked(useMutation).mockReturnValue(vi.fn() as unknown as ReturnType<typeof useMutation>);
  render(<ReviewQueue />);
  const ready = screen.getByRole("region", { name: /Ready to publish/ });
  expect(within(ready).getByRole("button", { name: "Submit pull request" })).toBeTruthy();
  expect(within(ready).getByText("Ready collection")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: /Submitted pull requests/ })).getByText("Submitted collection")).toBeTruthy();
  const history = screen.getByText("Completed projects").closest("details")!;
  expect(within(history).queryByText("Ready collection")).toBeNull();
  expect(within(history).queryByText("Submitted collection")).toBeNull();
  expect(within(history).getByText("Historical collection")).toBeTruthy();
});
