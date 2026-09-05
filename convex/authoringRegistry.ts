import { v } from "convex/values";

import {
  capabilityRegistrySha256,
  parseCapabilityRegistry,
  type AuthoringCapabilityRegistry,
} from "../packages/authoring-pipeline/src/contracts.ts";
import {
  internalMutation,
  internalQuery,
  type MutationCtx,
  type QueryCtx,
} from "./_generated/server";

export interface ActiveRegistryPointer {
  kind: "watchcraft.authoring-active-registry";
  schema_version: 1;
  environment: string;
  revision: number;
  registry_version: string;
  registry_sha256: string;
  activated_at: number;
  activated_by: string;
  last_command_id: string;
}

type ReadableCtx = MutationCtx | QueryCtx;

async function versionByName(ctx: ReadableCtx, registryVersion: string) {
  return ctx.db
    .query("authoring_registry_versions")
    .withIndex("by_registry_version", (query) => query.eq("registry_version", registryVersion))
    .unique();
}

async function activePointerDocument(ctx: ReadableCtx, environment: string) {
  return ctx.db
    .query("authoring_registry_active")
    .withIndex("by_environment", (query) => query.eq("environment", environment))
    .unique();
}

function parseActivePointer(value: unknown): ActiveRegistryPointer {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("Active registry pointer must be an object.");
  }
  const pointer = value as Record<string, unknown>;
  if (
    pointer.kind !== "watchcraft.authoring-active-registry"
    || pointer.schema_version !== 1
    || typeof pointer.environment !== "string"
    || typeof pointer.revision !== "number"
    || typeof pointer.registry_version !== "string"
    || typeof pointer.registry_sha256 !== "string"
    || typeof pointer.activated_at !== "number"
    || typeof pointer.activated_by !== "string"
    || typeof pointer.last_command_id !== "string"
  ) {
    throw new TypeError("Active registry pointer is invalid.");
  }
  return pointer as unknown as ActiveRegistryPointer;
}

export async function activeRegistry(
  ctx: ReadableCtx,
  environment: string,
): Promise<{ active: ActiveRegistryPointer; registry: AuthoringCapabilityRegistry } | null> {
  const activeDocument = await activePointerDocument(ctx, environment);
  if (!activeDocument) return null;
  const active = parseActivePointer(activeDocument.aggregate);
  const version = await versionByName(ctx, active.registry_version);
  if (!version || version.registry_sha256 !== active.registry_sha256) {
    throw new Error(`Active registry ${active.registry_version} is missing or inconsistent.`);
  }
  const registry = parseCapabilityRegistry(version.document);
  if (capabilityRegistrySha256(registry) !== active.registry_sha256) {
    throw new Error(`Stored registry ${active.registry_version} failed digest verification.`);
  }
  return { active, registry };
}

export const getActiveRegistry = internalQuery({
  args: { environment: v.string() },
  returns: v.any(),
  handler: async (ctx, args) => (await activeRegistry(ctx, args.environment)) ?? {
    active: null,
    registry: null,
  },
});

export const publishRegistry = internalMutation({
  args: {
    command_id: v.string(),
    actor: v.string(),
    registry: v.any(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const registry = parseCapabilityRegistry(args.registry);
    const registrySha256 = capabilityRegistrySha256(registry);
    const commandReplay = await ctx.db
      .query("authoring_registry_versions")
      .withIndex("by_publish_command", (query) => query.eq("command_id", args.command_id))
      .unique();
    if (commandReplay) {
      if (commandReplay.registry_sha256 !== registrySha256) {
        throw new Error(`Registry publication command ${args.command_id} does not match its original document.`);
      }
      return commandReplay;
    }
    const existing = await versionByName(ctx, registry.registry_version);
    if (existing) {
      if (existing.registry_sha256 !== registrySha256) {
        throw new Error(`Registry version ${registry.registry_version} is immutable.`);
      }
      return existing;
    }
    const createdAt = Date.now();
    const id = await ctx.db.insert("authoring_registry_versions", {
      registry_version: registry.registry_version,
      registry_sha256: registrySha256,
      document: registry,
      created_at: createdAt,
      created_by: args.actor,
      command_id: args.command_id,
    });
    return ctx.db.get(id);
  },
});

export const activateRegistry = internalMutation({
  args: {
    environment: v.string(),
    command_id: v.string(),
    actor: v.string(),
    registry_version: v.string(),
    registry_sha256: v.string(),
    expected_revision: v.number(),
  },
  returns: v.any(),
  handler: async (ctx, args) => {
    const replay = await ctx.db
      .query("authoring_registry_events")
      .withIndex("by_environment_command", (query) => query
        .eq("environment", args.environment)
        .eq("command_id", args.command_id))
      .unique();
    if (replay) return parseActivePointer(replay.result);

    const version = await versionByName(ctx, args.registry_version);
    if (!version || version.registry_sha256 !== args.registry_sha256) {
      throw new Error(`Unknown registry ${args.registry_version} with digest ${args.registry_sha256}.`);
    }
    const stored = await activePointerDocument(ctx, args.environment);
    const current = stored ? parseActivePointer(stored.aggregate) : null;
    const currentRevision = current?.revision ?? 0;
    if (currentRevision !== args.expected_revision) {
      throw new Error(
        `Registry revision conflict for ${args.environment}: expected ${args.expected_revision}, found ${currentRevision}.`,
      );
    }
    const now = Date.now();
    const next: ActiveRegistryPointer = {
      kind: "watchcraft.authoring-active-registry",
      schema_version: 1,
      environment: args.environment,
      revision: currentRevision + 1,
      registry_version: args.registry_version,
      registry_sha256: args.registry_sha256,
      activated_at: now,
      activated_by: args.actor,
      last_command_id: args.command_id,
    };
    if (stored) {
      await ctx.db.replace(stored._id, { environment: args.environment, aggregate: next });
    } else {
      await ctx.db.insert("authoring_registry_active", { environment: args.environment, aggregate: next });
    }
    await ctx.db.insert("authoring_registry_events", {
      environment: args.environment,
      command_id: args.command_id,
      actor: args.actor,
      from_revision: currentRevision,
      from_registry_sha256: current?.registry_sha256,
      to_registry_sha256: args.registry_sha256,
      revision: next.revision,
      recorded_at: now,
      result: next,
    });
    return next;
  },
});
