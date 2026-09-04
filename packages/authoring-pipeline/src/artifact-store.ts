import {
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
  type S3ClientConfig,
} from "@aws-sdk/client-s3";

import {
  type ArtifactReference,
  type JsonValue,
  artifactKey,
  canonicalJson,
  parseArtifactReference,
  sha256Hex,
} from "./contracts.ts";

interface S3Sender {
  send(command: unknown): Promise<unknown>;
}

export interface R2ArtifactStoreConfig {
  endpoint: string;
  bucket: string;
  accessKeyId: string;
  secretAccessKey: string;
}

export interface ArtifactDescription {
  artifactKind: string;
  mediaType: string;
  schema: {
    id: string;
    version: number;
  };
}

function isNotFound(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { name?: unknown; $metadata?: { httpStatusCode?: unknown } };
  return candidate.name === "NotFound"
    || candidate.name === "NoSuchKey"
    || candidate.$metadata?.httpStatusCode === 404;
}

function isPreconditionFailure(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { name?: unknown; $metadata?: { httpStatusCode?: unknown } };
  return candidate.name === "PreconditionFailed" || candidate.$metadata?.httpStatusCode === 412;
}

async function bodyBytes(body: unknown): Promise<Uint8Array> {
  if (!body || typeof body !== "object") throw new Error("R2 returned an empty object body.");
  const candidate = body as {
    transformToByteArray?: () => Promise<Uint8Array>;
    [Symbol.asyncIterator]?: () => AsyncIterator<Uint8Array>;
  };
  if (candidate.transformToByteArray) return candidate.transformToByteArray();
  if (candidate[Symbol.asyncIterator]) {
    const chunks: Uint8Array[] = [];
    let length = 0;
    for await (const chunk of candidate as AsyncIterable<Uint8Array>) {
      chunks.push(chunk);
      length += chunk.byteLength;
    }
    const result = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      result.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return result;
  }
  throw new Error("R2 returned an unsupported object body.");
}

export class R2ArtifactStore {
  readonly bucket: string;
  readonly client: S3Sender;

  constructor(config: R2ArtifactStoreConfig, client?: S3Sender) {
    if (!config.bucket) throw new TypeError("R2 bucket is required.");
    this.bucket = config.bucket;
    const clientConfig: S3ClientConfig = {
      region: "auto",
      endpoint: config.endpoint.replace(/\/$/, ""),
      credentials: {
        accessKeyId: config.accessKeyId,
        secretAccessKey: config.secretAccessKey,
      },
    };
    this.client = client ?? new S3Client(clientConfig);
  }

  async putJson(value: JsonValue, description: ArtifactDescription): Promise<ArtifactReference> {
    return this.putBytes(
      new TextEncoder().encode(canonicalJson(value)),
      description,
    );
  }

  async putBytes(bytes: Uint8Array, description: ArtifactDescription): Promise<ArtifactReference> {
    const digest = sha256Hex(bytes);
    const reference: ArtifactReference = {
      store: "r2",
      algorithm: "sha256",
      digest,
      byte_length: bytes.byteLength,
      media_type: description.mediaType,
      artifact_kind: description.artifactKind,
      schema: description.schema,
      key: artifactKey(digest),
    };

    let exists = false;
    try {
      await this.client.send(new HeadObjectCommand({ Bucket: this.bucket, Key: reference.key }));
      exists = true;
    } catch (error) {
      if (!isNotFound(error)) throw error;
    }

    if (!exists) {
      try {
        await this.client.send(new PutObjectCommand({
          Bucket: this.bucket,
          Key: reference.key,
          Body: bytes,
          ContentLength: bytes.byteLength,
          ContentType: description.mediaType,
          IfNoneMatch: "*",
          Metadata: {
            sha256: digest,
            artifact_kind: description.artifactKind,
            schema_id: description.schema.id,
            schema_version: String(description.schema.version),
          },
        }));
      } catch (error) {
        if (!isPreconditionFailure(error)) throw error;
      }
    }

    const stored = await this.getBytes(reference);
    if (stored.byteLength !== bytes.byteLength) {
      throw new Error(`Stored artifact ${reference.key} has the wrong byte length.`);
    }
    return reference;
  }

  async getBytes(untrustedReference: unknown): Promise<Uint8Array> {
    const reference = parseArtifactReference(untrustedReference);
    const response = await this.client.send(new GetObjectCommand({
      Bucket: this.bucket,
      Key: reference.key,
    })) as { Body?: unknown; ContentLength?: number };
    const bytes = await bodyBytes(response.Body);
    if (response.ContentLength !== undefined && response.ContentLength !== reference.byte_length) {
      throw new Error(`Artifact ${reference.key} has an unexpected declared length.`);
    }
    if (bytes.byteLength !== reference.byte_length || sha256Hex(bytes) !== reference.digest) {
      throw new Error(`Artifact ${reference.key} failed content verification.`);
    }
    return bytes;
  }
}

export function r2ConfigFromEnvironment(environment = process.env): R2ArtifactStoreConfig {
  const endpoint = environment.WATCHCRAFT_R2_ENDPOINT;
  const bucket = environment.WATCHCRAFT_R2_BUCKET;
  const accessKeyId = environment.WATCHCRAFT_R2_ACCESS_KEY_ID;
  const secretAccessKey = environment.WATCHCRAFT_R2_SECRET_ACCESS_KEY;
  if (!endpoint || !bucket || !accessKeyId || !secretAccessKey) {
    throw new Error("Watchcraft R2 endpoint, bucket, access key ID, and secret access key are required.");
  }
  return { endpoint, bucket, accessKeyId, secretAccessKey };
}
