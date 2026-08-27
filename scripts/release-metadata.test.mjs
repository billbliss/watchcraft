import assert from "node:assert/strict";
import test from "node:test";
import { installerBundles, releaseMetadata, tauriChannelConfig } from "./release-metadata.mjs";

test("prerelease tags produce beta builds", () => {
  assert.deepEqual(releaseMetadata({ refType: "tag", refName: "v0.2.0-beta.3" }), {
    channel: "beta",
    prerelease: true,
    version: "0.2.0-beta.3",
  });
});

test("stable tags produce release builds", () => {
  assert.deepEqual(releaseMetadata({ refType: "tag", refName: "v1.0.0" }), {
    channel: "release",
    prerelease: false,
    version: "1.0.0",
  });
});

test("manual builds default to the requested channel and package version", () => {
  assert.deepEqual(
    releaseMetadata({ requestedChannel: "beta", baseVersion: "0.1.0" }),
    { channel: "beta", prerelease: true, version: "0.1.0" },
  );
});

test("beta builds use a separate product and application identity", () => {
  const config = tauriChannelConfig({ channel: "beta", version: "0.2.0-beta.1" });
  assert.equal(config.productName, "Watchcraft Beta");
  assert.equal(config.identifier, "app.watchcraft.reader.beta");
  assert.equal(config.version, "0.2.0-beta.1");
});

test("release builds preserve the production identity", () => {
  assert.deepEqual(tauriChannelConfig({ channel: "release", version: "1.0.0" }), {
    version: "1.0.0",
  });
});

test("Windows beta builds use NSIS without the MSI prerelease restriction", () => {
  assert.equal(installerBundles({ runnerOs: "Windows", channel: "beta" }), "nsis");
});

test("Windows stable builds retain both installer formats", () => {
  assert.equal(installerBundles({ runnerOs: "Windows", channel: "release" }), "nsis,msi");
});

test("Linux and macOS installer formats do not vary by channel", () => {
  assert.equal(installerBundles({ runnerOs: "Linux", channel: "beta" }), "deb,appimage");
  assert.equal(installerBundles({ runnerOs: "macOS", channel: "release" }), "dmg");
});
