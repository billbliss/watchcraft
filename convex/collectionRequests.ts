import { ConvexError, v } from "convex/values";
import { action, internalMutation, internalQuery, mutation, query, type QueryCtx } from "./_generated/server";
import { internal } from "./_generated/api";
import type { Doc, Id } from "./_generated/dataModel";
import { sha256Hex } from "../packages/authoring-pipeline/src/contracts";
import { parseYouTubeSource } from "../packages/catalog-core/src/youtubeRequest";
import { discover, existingCollections, type ExistingCollection, type Discovery } from "./requestDiscovery";
import { portalIdentity } from "./portal";
const scope = v.union(v.literal("video"), v.literal("playlist"), v.literal("popular"), v.literal("channel"));
function tokenHash(token: string) {
  if (!/^[a-f0-9]{64}$/.test(token)) throw new ConvexError("Invalid status link.");
  return sha256Hex(token);
}
function trustedIdentity(identity: Awaited<ReturnType<QueryCtx["auth"]["getUserIdentity"]>>) {
  return identity && process.env.CLERK_JWT_ISSUER_DOMAIN && identity.issuer === process.env.CLERK_JWT_ISSUER_DOMAIN ? identity : null;
}
export const preview = action({
  args: { source: v.string() },
  handler: async (ctx, args): Promise<Discovery & { existing: ExistingCollection[]; alreadyRequested: boolean }> => {
    try {
      const source = parseYouTubeSource(args.source);
      const [data, existing, alreadyRequested] = await Promise.all([discover(source.url), existingCollections(source), ctx.runQuery(internal.collectionRequests.alreadyRequested, { sourceKey: source.key })]);
      return { ...data, existing, alreadyRequested };
    }
    catch { throw new ConvexError("Use a YouTube video, saved playlist, or channel link."); }
  },
});
export const submit = action({
  args: { source: v.string(), preferredScope: scope, token: v.string(), attachAccount: v.boolean() },
  handler: async (ctx, args): Promise<{ requestId: Id<"collection_requests">; duplicate: boolean }> => {
    const token_sha256 = tokenHash(args.token);
    let source;
    try { source = parseYouTubeSource(args.source); } catch { throw new ConvexError("Use a valid YouTube link."); }
    const identity = args.attachAccount ? trustedIdentity(await ctx.auth.getUserIdentity()) : null;
    if (args.attachAccount && !identity) throw new ConvexError("Sign in before adding this request to your account.");
    const owner = identity?.tokenIdentifier;
    const replay = await ctx.runQuery(internal.collectionRequests.findReceipt, { token_sha256 });
    if (replay) {
      if (replay.sourceKey !== source.key || replay.preferredScope !== args.preferredScope || replay.owner !== (owner ?? null)) throw new ConvexError("This status link belongs to another request.");
      return { requestId: replay.requestId, duplicate: true };
    }
    const data = await discover(source.url);
    if (!data.options.some(option => option.scope === args.preferredScope)) throw new ConvexError("That scope could not be verified. Check the link again or choose another scope.");
    return ctx.runMutation(internal.collectionRequests.record, {
      data, preferredScope: args.preferredScope, token_sha256,
      ...(identity ? { owner: identity.tokenIdentifier, owner_label: (identity.email ?? identity.name ?? "Signed-in requester").slice(0, 200) } : {}),
    });
  },
});
export const alreadyRequested = internalQuery({
  args: { sourceKey: v.string() },
  handler: async (ctx, args) => Boolean(await ctx.db.query("collection_requests").withIndex("by_source", q => q.eq("source_key", args.sourceKey)).unique()),
});
export const findReceipt = internalQuery({
  args: { token_sha256: v.string() },
  handler: async (ctx, args) => {
    const receipt = await ctx.db.query("collection_request_receipts").withIndex("by_token", q => q.eq("token_sha256", args.token_sha256)).unique();
    if (!receipt) return null;
    const request = await ctx.db.get(receipt.request_id);
    return request ? { requestId: request._id, sourceKey: request.source_key, preferredScope: receipt.preferred_scope, owner: receipt.owner ?? null } : null;
  },
});
export const record = internalMutation({
  args: { data: v.any(), preferredScope: scope, token_sha256: v.string(), owner: v.optional(v.string()), owner_label: v.optional(v.string()) },
  handler: async (ctx, args) => {
    const data = args.data as Discovery;
    const previous = await ctx.db.query("collection_request_receipts").withIndex("by_token", q => q.eq("token_sha256", args.token_sha256)).unique();
    if (previous) {
      const request = await ctx.db.get(previous.request_id);
      if (request?.source_key !== data.source.key || previous.preferred_scope !== args.preferredScope || previous.owner !== args.owner) throw new ConvexError("This status link belongs to another request.");
      return { requestId: previous.request_id, duplicate: true };
    }
    // A global admission bound requires no IP address, cookie, or fingerprint.
    const recent = await ctx.db.query("collection_request_receipts").withIndex("by_created", q => q.gte("created_at", Date.now() - 60_000)).take(30);
    if (recent.length >= 30) throw new ConvexError("Requests are busy right now. Please try again in a minute.");
    const existing = await ctx.db.query("collection_requests").withIndex("by_source", q => q.eq("source_key", data.source.key)).unique();
    const now = Date.now();
    const requestId = existing?._id ?? await ctx.db.insert("collection_requests", {
      source_key: data.source.key, source: data.source, title: data.title, channel: data.channel, options: data.options,
      selected_scope: args.preferredScope, revision: 1, state: "submitted", created_at: now, updated_at: now,
    });
    await ctx.db.insert("collection_request_receipts", {
      token_sha256: args.token_sha256, request_id: requestId, preferred_scope: args.preferredScope, created_at: now,
      ...(args.owner ? { owner: args.owner, owner_label: args.owner_label } : {}),
    });
    return { requestId, duplicate: Boolean(existing) };
  },
});
async function publicStatus(ctx: QueryCtx, request: Doc<"collection_requests">, preferredScope: string) {
  const execution = request.execution_id ? await ctx.db.query("authoring_project_executions").withIndex("by_execution_id", q => q.eq("execution_id", request.execution_id!)).unique() : null;
  return { id: request._id, title: request.title, sourceUrl: request.source.url as string, preferredScope, selectedScope: request.selected_scope,
    state: request.state, processingState: execution?.aggregate.state as string | undefined ?? null,
    submittedAt: request.created_at, updatedAt: execution?.updated_at ?? request.updated_at };
}
export const status = query({
  args: { token: v.string() },
  handler: async (ctx, args) => {
    const hash = tokenHash(args.token);
    const receipt = await ctx.db.query("collection_request_receipts").withIndex("by_token", q => q.eq("token_sha256", hash)).unique();
    if (!receipt) return null;
    const request = await ctx.db.get(receipt.request_id);
    return request ? publicStatus(ctx, request, receipt.preferred_scope) : null;
  },
});
export const mine = query({
  args: {},
  handler: async ctx => {
    const identity = trustedIdentity(await ctx.auth.getUserIdentity());
    if (!identity) return [];
    const receipts = await ctx.db.query("collection_request_receipts").withIndex("by_owner", q => q.eq("owner", identity.tokenIdentifier)).order("desc").take(100);
    const unique = [...new Map(receipts.map(r => [r.request_id, r])).values()];
    return (await Promise.all(unique.map(async receipt => {
      const request = await ctx.db.get(receipt.request_id);
      return request ? publicStatus(ctx, request, receipt.preferred_scope) : null;
    }))).filter(item => item !== null);
  },
});
export const queue = query({
  args: {},
  handler: async ctx => {
    if (!await portalIdentity(ctx)) throw new ConvexError("Portal access denied.");
    const groups = await Promise.all(["submitted", "planning"].map(state => ctx.db.query("collection_requests").withIndex("by_state_created", q => q.eq("state", state as "submitted" | "planning")).take(51)));
    const records = groups.flat().sort((a,b) => a.created_at - b.created_at).slice(0, 50);
    const planner = await ctx.db.query("request_planners").withIndex("by_name", q => q.eq("name", "default")).unique();
    return { plannerHeartbeatAt: planner?.heartbeat_at ?? null, hasMore: groups.flat().length > 50, requests: await Promise.all(records.map(async r => {
      const receipts = await ctx.db.query("collection_request_receipts").withIndex("by_request", q => q.eq("request_id", r._id)).take(101);
      return { id: r._id, revision: r.revision, title: r.title, sourceUrl: r.source.url as string, options: r.options as Discovery["options"], selectedScope: r.selected_scope, state: r.state, preparation: r.preparation ? { stage: r.preparation.stage, updatedAt: r.preparation.updated_at, stalled: r.preparation.lease_until < Date.now() && r.preparation.stage !== "failed" } : null, submittedAt: r.created_at,
        requesters: receipts.slice(0,100).map(receipt => ({ label: receipt.owner_label ?? "Anonymous", scope: receipt.preferred_scope })), hasMoreRequesters: receipts.length > 100 };
    })) };
  },
});
export const reviewRequest = mutation({
  args: { requestId: v.id("collection_requests"), expectedRevision: v.number(), decision: v.union(v.literal("plan"), v.literal("reject")), selectedScope: scope },
  handler: async (ctx, args) => {
    if (!await portalIdentity(ctx)) throw new ConvexError("Portal access denied.");
    const request = await ctx.db.get(args.requestId);
    const nextState = args.decision === "reject" ? "rejected" : "planning";
    if (request?.revision === args.expectedRevision + 1 && request.state === nextState && request.selected_scope === args.selectedScope) return;
    if (!request || request.revision !== args.expectedRevision || !["submitted", "planning"].includes(request.state)) throw new ConvexError("This request changed. Refresh before deciding.");
    if (!(request.options as Discovery["options"]).some(option => option.scope === args.selectedScope)) throw new ConvexError("This scope hasn't been verified.");
    await ctx.db.patch(request._id, { selected_scope: args.selectedScope, state: nextState, preparation: undefined, revision: request.revision + 1, updated_at: Date.now() });
  },
});
// The operator uses this handoff to prepare the normal immutable project plan.
export const planningRequests = internalQuery({
  args: {},
  handler: async ctx => ({ requests: await ctx.db.query("collection_requests").withIndex("by_state_created", q => q.eq("state", "planning")).take(50) }),
});
export const linkExecution = internalMutation({
  args: { request_id: v.id("collection_requests"), expected_revision: v.number(), execution_id: v.string() },
  handler: async (ctx, args) => {
    const request = await ctx.db.get(args.request_id);
    if (request?.state === "planned" && request.execution_id === args.execution_id) return;
    if (!request || request.state !== "planning" || request.revision !== args.expected_revision) throw new Error("Request changed while its plan was being prepared.");
    const execution = await ctx.db.query("authoring_project_executions").withIndex("by_execution_id", q => q.eq("execution_id", args.execution_id)).unique();
    if (!execution || execution.aggregate.state !== "awaiting_approval") throw new Error("Link a pending execution so its exact work can be reviewed.");
    const videoId = request.source.videoId as string | undefined;
    if (videoId && !execution.aggregate.selection.item_ids.includes(`youtube:${videoId}`)) throw new Error("The plan must include the requested video.");
    if (request.selected_scope === "video" && execution.aggregate.selection.item_ids.length !== 1) throw new Error("A single-video request must select exactly one video.");
    await ctx.db.patch(request._id, { execution_id: args.execution_id, state: "planned", revision: request.revision + 1, updated_at: Date.now() });
  },
});

// Operator-only preparation progress. A lease prevents duplicate planners from
// preparing different snapshots for the same request revision.
export const preparationRequest = internalQuery({
  args: { request_id: v.id("collection_requests") },
  handler: async (ctx, args) => {
    const request = await ctx.db.get(args.request_id);
    if (!request) return null;
    const projectId = `request-${request._id}-r${request.revision}`.toLowerCase();
    const project = await ctx.db.query("authoring_catalog_projects").withIndex("by_project_id", q => q.eq("project_id", projectId)).unique();
    return { ...request, prepared_project: project?.aggregate ?? null };
  },
});
export const preparationProgress = internalMutation({
  args: { request_id: v.id("collection_requests"), expected_revision: v.number(), attempt_id: v.string(),
    stage: v.union(v.literal("discovering"), v.literal("snapshot"), v.literal("estimating"), v.literal("linking"), v.literal("failed")) },
  handler: async (ctx, args) => {
    const request = await ctx.db.get(args.request_id);
    if (!request || request.state !== "planning" || request.revision !== args.expected_revision) throw new Error("Request changed while its plan was being prepared.");
    const previous = request.preparation;
    if (previous && previous.attempt_id !== args.attempt_id && previous.stage !== "failed" && previous.lease_until > Date.now()) throw new Error("Another operator is preparing this request.");
    if ((!previous || previous.attempt_id !== args.attempt_id) && args.stage !== "discovering") throw new Error("Start preparation with discovery.");
    await ctx.db.patch(request._id, { preparation: { attempt_id: args.attempt_id, stage: args.stage, lease_until: Date.now() + 30 * 60_000, updated_at: Date.now() } });
    return { updated: true };
  },
});

export const createPreparedExecution = internalMutation({
  args: { request_id: v.id("collection_requests"), expected_revision: v.number(), attempt_id: v.string(),
    command_id: v.string(), execution: v.any(), submitted_by: v.optional(v.string()) },
  handler: async (ctx, args): Promise<any> => {
    const request = await ctx.db.get(args.request_id);
    if (!request || request.state !== "planning" || request.revision !== args.expected_revision || request.preparation?.attempt_id !== args.attempt_id || request.preparation.stage !== "linking") throw new Error("Request changed while its plan was being prepared.");
    const projectId = `request-${request._id}-r${request.revision}`.toLowerCase();
    if (args.execution?.project?.project_id !== projectId) throw new Error("The plan belongs to another request.");
    const project = await ctx.db.query("authoring_catalog_projects").withIndex("by_project_id", q => q.eq("project_id", projectId)).unique();
    const entries = project?.aggregate?.iterator?.configuration?.entries;
    const selected = args.execution?.selection?.item_ids;
    if (!Array.isArray(entries) || !Array.isArray(selected) || selected.length !== entries.length || entries.some((entry: any, i: number) => entry.item_id !== selected[i])) throw new Error("The plan must include the complete requested snapshot.");
    // Nested mutations share this transaction: a stale request cannot leave an
    // orphan approval card or expose a plan before its requester is attached.
    const result = await ctx.runMutation(internal.authoringInternal.createProjectExecutionRecord, {
      command_id: args.command_id, execution: args.execution, ...(args.submitted_by ? { submitted_by: args.submitted_by } : {}),
    });
    await ctx.runMutation(internal.collectionRequests.linkExecution, { request_id: args.request_id, expected_revision: args.expected_revision, execution_id: args.execution.execution_id });
    return result;
  },
});

export const pollPlanner = internalMutation({
  args: { runner_id: v.string() },
  handler: async (ctx, args) => {
    if (!/^[a-zA-Z0-9-]{1,100}$/.test(args.runner_id)) throw new Error("Invalid planner identifier.");
    const previous = await ctx.db.query("request_planners").withIndex("by_name", q => q.eq("name", "default")).unique();
    if (previous && previous.runner_id !== args.runner_id && previous.heartbeat_at > Date.now() - 60_000) throw new Error("Another planner is already connected.");
    if (previous) await ctx.db.patch(previous._id, { runner_id: args.runner_id, heartbeat_at: Date.now() });
    else await ctx.db.insert("request_planners", { name: "default", runner_id: args.runner_id, heartbeat_at: Date.now() });
    // Failed and interrupted requests require the owner's explicit Retry action.
    const requests = await ctx.db.query("collection_requests").withIndex("by_planning_stage", q => q.eq("state", "planning").eq("preparation.stage", undefined)).take(1);
    return { requests: requests.map(r => ({ request_id: r._id, expected_revision: r.revision })) };
  },
});
export const disconnectPlanner = internalMutation({
  args: { runner_id: v.string() },
  handler: async (ctx, args) => {
    const previous = await ctx.db.query("request_planners").withIndex("by_name", q => q.eq("name", "default")).unique();
    if (previous?.runner_id === args.runner_id) await ctx.db.delete(previous._id);
    return { disconnected: previous?.runner_id === args.runner_id };
  },
});
