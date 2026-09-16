import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  portal_workflows: defineTable({
    execution_id: v.string(), phase: v.string(), state: v.string(),
    runner_id: v.optional(v.string()), lease_until: v.number(), updated_at: v.number(),
    compilation_job_id: v.optional(v.string()), preview_url: v.optional(v.string()),
    preview_branch: v.optional(v.string()), preview_commit: v.optional(v.string()),
    pull_request_url: v.optional(v.string()),
    pull_request_status: v.optional(v.union(v.literal("open"), v.literal("closed"), v.literal("merged"))),
    pull_request_checked_at: v.optional(v.number()),
    pull_request_merged_at: v.optional(v.number()),
    failure: v.optional(v.object({ message: v.string(), occurred_at: v.number() })),
  }).index("by_execution", ["execution_id"]).index("by_state_lease", ["state", "lease_until"]),
  request_planners: defineTable({
    name: v.string(), runner_id: v.string(), heartbeat_at: v.number(),
  }).index("by_name", ["name"]),
  collection_requests: defineTable({
    source_key: v.string(), source: v.any(), title: v.string(), channel: v.union(v.string(), v.null()),
    options: v.any(), selected_scope: v.string(), revision: v.number(),
    state: v.union(v.literal("submitted"), v.literal("planning"), v.literal("planned"), v.literal("rejected")),
    preparation: v.optional(v.object({
      attempt_id: v.string(), stage: v.string(), lease_until: v.number(),
      updated_at: v.number(),
    })),
    execution_id: v.optional(v.string()), created_at: v.number(), updated_at: v.number(),
  }).index("by_source", ["source_key"]).index("by_state_created", ["state", "created_at"])
    .index("by_execution", ["execution_id"]).index("by_planning_stage", ["state", "preparation.stage", "created_at"]),
  collection_request_receipts: defineTable({
    token_sha256: v.string(), request_id: v.id("collection_requests"), preferred_scope: v.string(), created_at: v.number(),
    owner: v.optional(v.string()), owner_label: v.optional(v.string()),
  }).index("by_token", ["token_sha256"]).index("by_owner", ["owner", "created_at"])
    .index("by_request", ["request_id"]).index("by_created", ["created_at"]),
  authoring_runs: defineTable({
    run_id: v.string(),
    aggregate: v.any(),
  }).index("by_run_id", ["run_id"]),
  authoring_jobs: defineTable({
    job_id: v.string(),
    aggregate: v.any(),
  }).index("by_job_id", ["job_id"])
    .index("by_state_updated", ["aggregate.state", "aggregate.updated_at"]),
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
  authoring_cleanup_events: defineTable({
    command_id: v.string(),
    target_kind: v.string(),
    target_id: v.string(),
    actor: v.string(),
    recorded_at: v.number(),
    result: v.any(),
  })
    .index("by_cleanup_command", ["command_id"])
    .index("by_cleanup_target", ["target_kind", "target_id"]),
  authoring_catalog_projects: defineTable({
    project_id: v.string(),
    current_revision: v.number(),
    aggregate: v.any(),
    updated_at: v.number(),
  }).index("by_project_id", ["project_id"]),
  authoring_catalog_project_revisions: defineTable({
    project_id: v.string(),
    revision: v.number(),
    aggregate: v.any(),
    transition: v.string(),
    actor: v.string(),
    command_id: v.string(),
    candidate_job_id: v.optional(v.string()),
    recorded_at: v.number(),
    result: v.any(),
  })
    .index("by_project_revision", ["project_id", "revision"])
    .index("by_project_command", ["project_id", "command_id"]),
  authoring_project_executions: defineTable({
    execution_id: v.string(),
    project_id: v.string(),
    aggregate: v.any(),
    updated_at: v.number(),
    submitted_by: v.optional(v.string()),
  })
    .index("by_execution_id", ["execution_id"])
    .index("by_updated", ["updated_at"])
    .index("by_state_updated", ["aggregate.state", "updated_at"])
    .index("by_project_updated", ["project_id", "updated_at"]),
  authoring_project_execution_events: defineTable({
    execution_id: v.string(),
    command_id: v.string(),
    command_sha256: v.string(),
    from_state: v.optional(v.string()),
    to_state: v.string(),
    revision: v.number(),
    recorded_at: v.number(),
    result: v.any(),
  }).index("by_execution_command", ["execution_id", "command_id"]),
  portal_review_events: defineTable({
    command_id: v.string(),
    execution_id: v.string(),
    decision: v.union(v.literal("accept"), v.literal("reject")),
    expected_revision: v.number(),
    approval_sha256: v.string(),
    actor: v.string(),
    actor_label: v.string(),
    recorded_at: v.number(),
  }).index("by_command", ["command_id"]),
});
