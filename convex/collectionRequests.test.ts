/// <reference types="vite/client" />
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { convexTest } from "convex-test";
import { api, internal } from "./_generated/api";
import schema from "./schema";
import { sha256Hex } from "../packages/authoring-pipeline/src/contracts";
import { parseYouTubeSource } from "../packages/catalog-core/src/youtubeRequest";
import { embeddedJson } from "./requestDiscovery";
const modules = import.meta.glob(["./**/*.{ts,js}", "!./**/*.test.ts", "!./vitest.config.mts"]);
const issuer = "https://test.clerk.accounts.dev";
const owner = { issuer, subject: "owner" };
const data = { source: parseYouTubeSource("https://youtu.be/PjObX9XQvgI"), title: "Requested video", channel: "Channel", thumbnail: null,
  options: [{ scope: "video", title: "Just this video", targetUrl: "https://www.youtube.com/watch?v=PjObX9XQvgI", count: 1 }], warning: null };
const token = "a".repeat(64);
beforeEach(() => { vi.stubEnv("CLERK_JWT_ISSUER_DOMAIN", issuer); vi.stubEnv("CLERK_PORTAL_USER_ID", owner.subject); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
function record(t: ReturnType<typeof convexTest>, extra = {}) { return t.mutation(internal.collectionRequests.record, { data, preferredScope: "video", token_sha256: sha256Hex(token), ...extra }); }

test("anonymous receipts have no identity, store only a token hash, and expose only status", async () => {
  const t = convexTest(schema, modules); await record(t);
  const stored = await t.run(ctx => ctx.db.query("collection_request_receipts").first());
  expect(stored).not.toHaveProperty("owner"); expect(stored).not.toHaveProperty("owner_label");
  expect(stored?.token_sha256).not.toBe(token);
  expect(await t.query(api.collectionRequests.status, { token })).toMatchObject({ title: data.title, state: "submitted", preferredScope: "video" });
  expect(await t.query(api.collectionRequests.status, { token: "b".repeat(64) })).toBeNull();
  await expect(t.query(api.collectionRequests.status, { token: "guessable" })).rejects.toThrow("Invalid status link");
  expect(await t.query(api.collectionRequests.mine)).toEqual([]);
});
test("duplicates share one request; retries do not add receipts or change attribution", async () => {
  const t = convexTest(schema, modules); const first = await record(t); await record(t);
  const second = await record(t, { token_sha256: sha256Hex("b".repeat(64)) });
  expect(first.requestId).toBe(second.requestId); expect(second.duplicate).toBe(true);
  expect(await t.run(ctx => ctx.db.query("collection_requests").collect())).toHaveLength(1);
  expect(await t.run(ctx => ctx.db.query("collection_request_receipts").collect())).toHaveLength(2);
  await expect(record(t, { owner: "someone" })).rejects.toThrow("belongs to another request");
});
test("history is private to the signed-in requester, without granting portal rights", async () => {
  const t = convexTest(schema, modules);
  const user = t.withIdentity({ issuer, subject: "requester", tokenIdentifier: "requester-token" });
  await record(t, { owner: "requester-token", owner_label: "Requester's name" });
  expect(await user.query(api.collectionRequests.mine)).toHaveLength(1);
  expect(await t.withIdentity(owner).query(api.collectionRequests.mine)).toEqual([]);
  await expect(user.query(api.collectionRequests.queue)).rejects.toThrow("Portal access denied");
  expect(JSON.stringify(await t.query(api.collectionRequests.status, { token }))).not.toContain("Requester's name");
});
test("only the owner chooses a verified scope; stale updates cannot overwrite it", async () => {
  const t = convexTest(schema, modules); const { requestId } = await record(t);
  const args = { requestId, expectedRevision: 1, decision: "plan" as const, selectedScope: "video" as const };
  await expect(t.mutation(api.collectionRequests.reviewRequest, args)).rejects.toThrow("Portal access denied");
  const admin = t.withIdentity(owner);
  await expect(admin.mutation(api.collectionRequests.reviewRequest, { ...args, selectedScope: "popular" })).rejects.toThrow("hasn't been verified");
  await admin.mutation(api.collectionRequests.reviewRequest, args); await admin.mutation(api.collectionRequests.reviewRequest, args);
  await expect(admin.mutation(api.collectionRequests.reviewRequest, { ...args, decision: "reject" })).rejects.toThrow("changed");
  expect(await t.query(api.collectionRequests.status, { token })).toMatchObject({ state: "planning" });
  expect((await t.query(internal.collectionRequests.planningRequests)).requests).toHaveLength(1);
});
test("an execution must include the requested video before its status can be linked", async () => {
  const t = convexTest(schema, modules); const { requestId } = await record(t);
  await t.withIdentity(owner).mutation(api.collectionRequests.reviewRequest, { requestId, expectedRevision: 1, decision: "plan", selectedScope: "video" });
  const id = await t.run(ctx => ctx.db.insert("authoring_project_executions", { execution_id: "execution", project_id: "project", updated_at: 1, aggregate: { state: "awaiting_approval", selection: { item_ids: ["youtube:another"] } } }));
  const args = { request_id: requestId, expected_revision: 2, execution_id: "execution" };
  await expect(t.mutation(internal.collectionRequests.linkExecution, args)).rejects.toThrow("must include");
  await t.run(ctx => ctx.db.patch(id, { aggregate: { state: "awaiting_approval", selection: { item_ids: ["youtube:PjObX9XQvgI"] } } }));
  await t.mutation(internal.collectionRequests.linkExecution, args);
  expect(await t.query(api.collectionRequests.status, { token })).toMatchObject({ state: "planned", processingState: "awaiting_approval" });
});
test("submission validates its scope on the server, not browser metadata", async () => {
  const t = convexTest(schema, modules);
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("YouTube unavailable")));
  await expect(t.action(api.collectionRequests.submit, { source: data.source.url, preferredScope: "popular", token, attachAccount: false })).rejects.toThrow("could not be verified");
  await expect(t.action(api.collectionRequests.submit, { source: data.source.url, preferredScope: "video", token, attachAccount: true })).rejects.toThrow("Sign in");
  await t.action(api.collectionRequests.submit, { source: `${data.source.url}&si=private`, preferredScope: "video", token, attachAccount: false });
  const stored = await t.run(ctx => ctx.db.query("collection_requests").first());
  expect(stored?.source.url).toBe(data.source.url);
  expect(JSON.stringify(stored)).not.toContain("private");
});
test("embedded JSON handles braces and escaped quotes in titles", () => {
  const content = { title: 'A {title} with "quotes"', rows: [1,2] };
  expect(embeddedJson(`var ytInitialData = ${JSON.stringify(content)}; trailing text`, "ytInitialData")).toEqual(content);
  expect(embeddedJson("not a YouTube response", "ytInitialData")).toBeNull();
});

test("public Popular selection follows the explicit provider command and includes the submitted video", async () => {
  const video = "PjObX9XQvgI";
  const channelPage = `var ytInitialData = ${JSON.stringify({ metadata: { channelMetadataRenderer: { title: "Channel", externalId: "UCYO_jab_esuFRV4b17AJtAw" } }, chipViewModel: { text: "Popular", selected: false, tapCommand: { innertubeCommand: { continuationCommand: { token: "popular-command" } } } }, lockupViewModel: { contentType: "LOCKUP_CONTENT_TYPE_VIDEO", contentId: "other-video" } })}; "INNERTUBE_CLIENT_VERSION":"test-version"`;
  const fetchMock = vi.fn(async (url: URL | string, options?: RequestInit) => {
    const value = String(url);
    if (value.includes("oembed")) return new Response(JSON.stringify({ title: "Requested video", author_name: "Channel", author_url: "https://www.youtube.com/@channel" }));
    if (value.includes("youtubei/v1/browse")) {
      expect(JSON.parse(String(options?.body))).toMatchObject({ continuation: "popular-command" });
      return new Response(JSON.stringify({ contents: [{ lockupViewModel: { contentType: "LOCKUP_CONTENT_TYPE_VIDEO", contentId: video } }] }));
    }
    return new Response(channelPage);
  });
  vi.stubGlobal("fetch", fetchMock);
  const { discover } = await import("./requestDiscovery");
  const result = await discover(`https://youtu.be/${video}`);
  expect(result.options.map(option => option.scope)).toEqual(["video", "popular", "channel"]);
  expect(result.options.find(option => option.scope === "popular")?.count).toBe(1);
});

test("an already signed-in visitor can explicitly submit without account attribution", async () => {
  const t = convexTest(schema, modules).withIdentity({ issuer, subject: "requester", email: "requester@example.com" });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("YouTube unavailable")));
  await t.action(api.collectionRequests.submit, { source: data.source.url, preferredScope: "video", token, attachAccount: false });
  const receipt = await t.run(ctx => ctx.db.query("collection_request_receipts").first());
  expect(receipt).not.toHaveProperty("owner");
  expect(receipt).not.toHaveProperty("owner_label");
});

test("preparation leases reject competing planners and stale request revisions", async () => {
  const t = convexTest(schema, modules); const { requestId } = await record(t);
  await t.withIdentity(owner).mutation(api.collectionRequests.reviewRequest, { requestId, expectedRevision: 1, decision: "plan", selectedScope: "video" });
  const args = { request_id: requestId, expected_revision: 2, attempt_id: "first", stage: "discovering" as const };
  expect(await t.mutation(internal.collectionRequests.preparationProgress, args)).toEqual({ updated: true });
  await expect(t.mutation(internal.collectionRequests.preparationProgress, { ...args, attempt_id: "second" })).rejects.toThrow("Another operator");
  await t.mutation(internal.collectionRequests.preparationProgress, { ...args, stage: "failed" });
  await t.mutation(internal.collectionRequests.preparationProgress, { ...args, attempt_id: "second" });
  await t.withIdentity(owner).mutation(api.collectionRequests.reviewRequest, { requestId, expectedRevision: 2, decision: "reject", selectedScope: "video" });
  await expect(t.mutation(internal.collectionRequests.preparationProgress, { ...args, attempt_id: "second", stage: "estimating" })).rejects.toThrow("Request changed");
  const stored = await t.query(internal.collectionRequests.preparationRequest, { request_id: requestId });
  expect(stored?.preparation).toBeUndefined();
});
test("a stale preparation cannot leave an orphan execution awaiting approval", async () => {
  const t = convexTest(schema, modules); const { requestId } = await record(t);
  await expect(t.mutation(internal.collectionRequests.createPreparedExecution, { request_id: requestId, expected_revision: 1, attempt_id: "first", command_id: "create", execution: { execution_id: "orphan" } })).rejects.toThrow("Request changed");
  expect(await t.run(ctx => ctx.db.query("authoring_project_executions").collect())).toEqual([]);
});
test("the portal sees preparation progress without exposing operator attempt identifiers to requesters", async () => {
  const t = convexTest(schema, modules); const { requestId } = await record(t);
  await t.withIdentity(owner).mutation(api.collectionRequests.reviewRequest, { requestId, expectedRevision: 1, decision: "plan", selectedScope: "video" });
  await t.mutation(internal.collectionRequests.preparationProgress, { request_id: requestId, expected_revision: 2, attempt_id: "private-attempt", stage: "discovering" });
  expect((await t.withIdentity(owner).query(api.collectionRequests.queue)).requests[0].preparation?.stage).toBe("discovering");
  expect(JSON.stringify(await t.query(api.collectionRequests.status, { token }))).not.toContain("private-attempt");
});

test("the planner only picks marked requests and never retries failed work automatically", async () => {
  const t = convexTest(schema, modules); const { requestId } = await record(t);
  expect((await t.mutation(internal.collectionRequests.pollPlanner, { runner_id: "runner" })).requests).toEqual([]);
  await t.withIdentity(owner).mutation(api.collectionRequests.reviewRequest, { requestId, expectedRevision: 1, decision: "plan", selectedScope: "video" });
  expect((await t.mutation(internal.collectionRequests.pollPlanner, { runner_id: "runner" })).requests).toEqual([{ request_id: requestId, expected_revision: 2 }]);
  await t.mutation(internal.collectionRequests.preparationProgress, { request_id: requestId, expected_revision: 2, attempt_id: "attempt", stage: "discovering" });
  await t.mutation(internal.collectionRequests.preparationProgress, { request_id: requestId, expected_revision: 2, attempt_id: "attempt", stage: "failed" });
  expect((await t.mutation(internal.collectionRequests.pollPlanner, { runner_id: "runner" })).requests).toEqual([]);
  await t.withIdentity(owner).mutation(api.collectionRequests.reviewRequest, { requestId, expectedRevision: 2, decision: "plan", selectedScope: "video" });
  expect((await t.mutation(internal.collectionRequests.pollPlanner, { runner_id: "runner" })).requests[0].expected_revision).toBe(3);
});
test("planner connection is exclusive and only its owner can disconnect", async () => {
  const t = convexTest(schema, modules);
  await t.mutation(internal.collectionRequests.pollPlanner, { runner_id: "first" });
  await expect(t.mutation(internal.collectionRequests.pollPlanner, { runner_id: "second" })).rejects.toThrow("already connected");
  await t.mutation(internal.collectionRequests.disconnectPlanner, { runner_id: "second" });
  expect((await t.withIdentity(owner).query(api.collectionRequests.queue)).plannerHeartbeatAt).not.toBeNull();
  await t.mutation(internal.collectionRequests.disconnectPlanner, { runner_id: "first" });
  expect((await t.withIdentity(owner).query(api.collectionRequests.queue)).plannerHeartbeatAt).toBeNull();
});
