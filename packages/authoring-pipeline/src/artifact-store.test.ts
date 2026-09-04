import assert from "node:assert/strict";
import test from "node:test";

import { R2ArtifactStore, canonicalJson, type JsonValue } from "./index.ts";

class FakeBody {
  constructor(private readonly bytes: Uint8Array) {}
  async transformToByteArray() {
    return this.bytes;
  }
}

class FakeS3 {
  readonly objects = new Map<string, Uint8Array>();
  putCount = 0;

  async send(command: any): Promise<unknown> {
    const name = command.constructor.name;
    const key = command.input.Key as string;
    if (name === "HeadObjectCommand") {
      if (!this.objects.has(key)) {
        const error = new Error("Not found") as Error & { name: string };
        error.name = "NotFound";
        throw error;
      }
      return { ContentLength: this.objects.get(key)!.byteLength };
    }
    if (name === "PutObjectCommand") {
      if (this.objects.has(key) && command.input.IfNoneMatch === "*") {
        const error = new Error("Already exists") as Error & { name: string };
        error.name = "PreconditionFailed";
        throw error;
      }
      this.putCount += 1;
      this.objects.set(key, new Uint8Array(command.input.Body));
      return {};
    }
    if (name === "GetObjectCommand") {
      const bytes = this.objects.get(key);
      if (!bytes) throw new Error("Missing fake object");
      return { Body: new FakeBody(bytes), ContentLength: bytes.byteLength };
    }
    throw new Error(`Unexpected command ${name}`);
  }
}

function store(client: FakeS3) {
  return new R2ArtifactStore({
    endpoint: "https://example.r2.cloudflarestorage.com",
    bucket: "test-bucket",
    accessKeyId: "test-access-key",
    secretAccessKey: "test-secret",
  }, client);
}

const description = {
  artifactKind: "transcript",
  mediaType: "application/json",
  schema: { id: "watchcraft.transcript", version: 1 },
};

test("content-addressed writes are create-once and verify exact stored bytes", async () => {
  const client = new FakeS3();
  const artifacts = store(client);
  const value: JsonValue = { text: "hello", segments: [] };
  const first = await artifacts.putJson(value, description);
  const second = await artifacts.putJson(value, description);

  assert.deepEqual(second, first);
  assert.equal(client.putCount, 1);
  assert.match(first.key, /^objects\/sha256\/[a-f0-9]{2}\/[a-f0-9]{62}$/);
  assert.equal(
    new TextDecoder().decode(await artifacts.getBytes(first)),
    canonicalJson(value),
  );
});

test("an existing corrupt object is never accepted by key alone", async () => {
  const client = new FakeS3();
  const artifacts = store(client);
  const reference = await artifacts.putJson({ text: "expected" }, description);
  client.objects.set(reference.key, new TextEncoder().encode("corrupt"));

  await assert.rejects(() => artifacts.getBytes(reference), /content verification|declared length/);
});
