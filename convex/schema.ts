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
});
