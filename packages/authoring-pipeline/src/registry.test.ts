import assert from "node:assert/strict";
import test from "node:test";

import {
  capabilityRegistrySha256,
  DEFAULT_CAPABILITY_REGISTRY,
  parseCapabilityRegistry,
  resolveJobSpecAgainstRegistry,
  verifyRegistryResolutionSnapshot,
} from "./index.ts";

const lexicalSpec = {
  operation: "generate" as const,
  artifact_kind: "analysis",
  output_schema: { id: "watchcraft.analysis.lexical", version: 1 },
  handler: { id: "watchcraft.analysis.lexical", version: "1" },
  source: { media_asset_id: "operator:lexical-analysis" },
  inputs: [],
  dependencies: [],
  configuration: { title: "Color workflow", text: "Balance exposure first." },
};

test("the checked-in registry is valid, stable, and fully resolves an approved job", () => {
  const registry = parseCapabilityRegistry(DEFAULT_CAPABILITY_REGISTRY);
  const spec = resolveJobSpecAgainstRegistry(lexicalSpec, registry);

  assert.equal(spec.registry_snapshot?.registry_version, "2026-09-04.1");
  assert.equal(spec.registry_snapshot?.registry_sha256, capabilityRegistrySha256(registry));
  assert.equal(spec.registry_snapshot?.execution_profile.id, "python-portable");
  assert.equal(spec.registry_snapshot?.execution_profile.dispatcher.workflow, "authoring-worker.yml");
  assert.deepEqual(verifyRegistryResolutionSnapshot(spec, registry), spec.registry_snapshot);
});

test("registry validation rejects duplicate identities and dangling profiles", () => {
  const registry = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  registry.handlers.push(structuredClone(registry.handlers[0]));
  assert.throws(() => parseCapabilityRegistry(registry), /handler identities must be unique/);

  const dangling = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  dangling.handlers[0].execution_profile.id = "missing";
  assert.throws(() => parseCapabilityRegistry(dangling), /references missing profile/);
});

test("resolution rejects unregistered behavior and worker verification rejects drift", () => {
  assert.throws(() => resolveJobSpecAgainstRegistry({
    ...lexicalSpec,
    output_schema: { id: "watchcraft.analysis.other", version: 1 },
  }, DEFAULT_CAPABILITY_REGISTRY), /output does not match/);

  const spec = resolveJobSpecAgainstRegistry(lexicalSpec, DEFAULT_CAPABILITY_REGISTRY);
  const changedRegistry = structuredClone(DEFAULT_CAPABILITY_REGISTRY);
  changedRegistry.execution_profiles[0].timeout_minutes += 1;
  assert.throws(
    () => verifyRegistryResolutionSnapshot(spec, changedRegistry),
    /not supported by this worker revision/,
  );
});
