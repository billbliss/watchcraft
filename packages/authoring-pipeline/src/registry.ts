import defaultRegistryJson from "../registry/default-registry.json" with { type: "json" };

import {
  capabilityRegistrySha256,
  canonicalJson,
  parseCapabilityRegistry,
  type AuthoringDependency,
  type ArtifactReference,
  type AuthoringCapabilityRegistry,
  type AuthoringJobSpec,
  type JsonValue,
  type RegistryArtifactContract,
  type RegistryResolutionSnapshot,
} from "./contracts.ts";

export const DEFAULT_CAPABILITY_REGISTRY = parseCapabilityRegistry(defaultRegistryJson);

function identity(id: string, version: string): string {
  return `${id}@${version}`;
}

function artifactMatches(
  reference: ArtifactReference | AuthoringDependency,
  contract: RegistryArtifactContract,
): boolean {
  return reference.artifact_kind === contract.artifact_kind
    && reference.schema.id === contract.schema.id
    && reference.schema.version === contract.schema.version;
}

function assertArtifactContracts(
  label: string,
  references: AuthoringDependency[],
  contracts: RegistryArtifactContract[],
): void {
  let referenceIndex = 0;
  contracts.forEach((contract, contractIndex) => {
    const minimum = contract.cardinality?.minimum ?? 1;
    const maximum = contract.cardinality?.maximum ?? 1;
    let count = 0;
    while (
      referenceIndex < references.length
      && count < maximum
      && artifactMatches(references[referenceIndex], contract)
    ) {
      referenceIndex += 1;
      count += 1;
    }
    if (count < minimum) {
      throw new TypeError(
        `${label} contract ${contractIndex} requires between ${minimum} and ${maximum} matching artifacts.`,
      );
    }
  });
  if (referenceIndex !== references.length) {
    throw new TypeError(`${label} contains artifacts outside the registered handler contract.`);
  }
}

export function resolveJobSpecAgainstRegistry(
  spec: AuthoringJobSpec,
  registryValue: unknown,
): AuthoringJobSpec {
  const registry = parseCapabilityRegistry(registryValue);
  const handler = registry.handlers.find(
    (candidate) => candidate.id === spec.handler.id && candidate.version === spec.handler.version,
  );
  if (!handler) {
    throw new TypeError(`Handler ${identity(spec.handler.id, spec.handler.version)} is not active.`);
  }
  if (handler.operation !== spec.operation) {
    throw new TypeError("Job operation does not match the registered handler contract.");
  }
  if (
    handler.output.artifact_kind !== spec.artifact_kind
    || handler.output.schema.id !== spec.output_schema.id
    || handler.output.schema.version !== spec.output_schema.version
  ) {
    throw new TypeError("Job output does not match the registered handler contract.");
  }
  assertArtifactContracts("Job input", spec.inputs, handler.inputs);
  assertArtifactContracts("Job dependency", spec.dependencies, handler.dependencies);

  const executionProfile = registry.execution_profiles.find(
    (candidate) => candidate.id === handler.execution_profile.id
      && candidate.version === handler.execution_profile.version,
  );
  if (!executionProfile) {
    throw new TypeError(
      `Execution profile ${identity(handler.execution_profile.id, handler.execution_profile.version)} is not active.`,
    );
  }
  return {
    ...spec,
    registry_snapshot: {
      registry_version: registry.registry_version,
      registry_sha256: capabilityRegistrySha256(registry),
      handler,
      execution_profile: executionProfile,
    },
  };
}

export function verifyRegistryResolutionSnapshot(
  spec: AuthoringJobSpec,
  localRegistryValue: unknown,
): RegistryResolutionSnapshot {
  if (!spec.registry_snapshot) {
    throw new TypeError("Job specification has no capability registry snapshot.");
  }
  const registry = parseCapabilityRegistry(localRegistryValue);
  const resolved = resolveJobSpecAgainstRegistry(
    { ...spec, registry_snapshot: undefined },
    registry,
  ).registry_snapshot as RegistryResolutionSnapshot;
  if (
    canonicalJson(spec.registry_snapshot as unknown as JsonValue)
    !== canonicalJson(resolved as unknown as JsonValue)
  ) {
    throw new TypeError("Job registry snapshot is not supported by this worker revision.");
  }
  return spec.registry_snapshot;
}

export function registryIdentity(registry: AuthoringCapabilityRegistry): {
  registry_version: string;
  registry_sha256: string;
} {
  return {
    registry_version: registry.registry_version,
    registry_sha256: capabilityRegistrySha256(registry),
  };
}
