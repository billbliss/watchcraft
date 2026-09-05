import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  authoring_runs: defineTable({
    run_id: v.string(),
    aggregate: v.any(),
  }).index("by_run_id", ["run_id"]),
  authoring_jobs: defineTable({
    job_id: v.string(),
    aggregate: v.any(),
  }).index("by_job_id", ["job_id"]),
  authoring_job_events: defineTable({
    job_id: v.string(),
    command_id: v.string(),
    from_state: v.optional(v.string()),
    to_state: v.string(),
    revision: v.number(),
    recorded_at: v.number(),
    result: v.any(),
  }).index("by_job_command", ["job_id", "command_id"]),
  authoring_run_events: defineTable({
    run_id: v.string(),
    command_id: v.string(),
    from_state: v.optional(v.string()),
    to_state: v.string(),
    revision: v.number(),
    recorded_at: v.number(),
    result: v.any(),
  }).index("by_run_command", ["run_id", "command_id"]),
  authoring_registry_versions: defineTable({
    registry_version: v.string(),
    registry_sha256: v.string(),
    document: v.any(),
    created_at: v.number(),
    created_by: v.string(),
    command_id: v.string(),
  })
    .index("by_registry_version", ["registry_version"])
    .index("by_registry_digest", ["registry_sha256"])
    .index("by_publish_command", ["command_id"]),
  authoring_registry_active: defineTable({
    environment: v.string(),
    aggregate: v.any(),
  }).index("by_environment", ["environment"]),
  authoring_registry_events: defineTable({
    environment: v.string(),
    command_id: v.string(),
    actor: v.string(),
    from_revision: v.number(),
    from_registry_sha256: v.optional(v.string()),
    to_registry_sha256: v.string(),
    revision: v.number(),
    recorded_at: v.number(),
    result: v.any(),
  }).index("by_environment_command", ["environment", "command_id"]),
});
