import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { createElement, useState } from "react";
import { JSDOM } from "jsdom";
import type { CollectionManifest } from "@watchcraft/catalog-core";
import { WebCollectionSettings } from "./WebCollectionSettings.tsx";
import {
  WEB_COLLECTIONS_KEY,
  WEB_LAST_COLLECTION_KEY,
  readWebCollections,
  saveWebCollection,
  type SavedWebCollection,
} from "./webCollectionRegistry.ts";

const FIRST_URL = "https://collections.example/first/collection.json";
const SECOND_URL = "https://collections.example/second/collection.json";
const FIRST_UPDATE_URL = "https://mirror.example/first/collection.json";

function featuredDirectory() {
  return {
    collections: [
      {
        collection_id: "first",
        title: "First collection",
        manifest_url: FIRST_URL,
        media_modes: ["remote"],
        video_count: 1,
      },
      {
        collection_id: "second",
        title: "Second collection",
        manifest_url: SECOND_URL,
        media_modes: ["remote"],
        video_count: 1,
      },
    ],
  };
}

const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", {
  url: "https://watchcraft.example/app/",
});
const globals = {
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  navigator: dom.window.navigator,
  localStorage: dom.window.localStorage,
  location: dom.window.location,
  window: dom.window,
  IS_REACT_ACT_ENVIRONMENT: true,
};
for (const [key, value] of Object.entries(globals)) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value,
    writable: true,
  });
}
const { cleanup, fireEvent, render, waitFor } = await import("@testing-library/react");

function manifest(
  collectionId: string,
  title: string,
  revision: number,
  hashDigit: string,
): CollectionManifest {
  return {
    kind: "watchcraft.collection",
    schema_version: 4,
    collection_id: collectionId,
    title,
    topic_scope: "collection",
    root: { type: "group", group_id: "root", title, children: [] },
    topics: {},
    topic_families: {},
    items: {},
    stats: { video_count: 0, topic_count: 0, topic_family_count: 0 },
    revision,
    content_hash: hashDigit.repeat(64),
  };
}

function installDom(): JSDOM {
  dom.window.localStorage.clear();
  dom.window.history.replaceState(null, "", "/app/");
  dom.window.document.body.innerHTML = '<div id="root"></div>';
  globalThis.fetch = async () => new Response(JSON.stringify({ collections: [] }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  return dom;
}

interface SettingsHarnessProps {
  manifests: Record<string, CollectionManifest>;
}

function SettingsHarness({ manifests }: SettingsHarnessProps) {
  const [collections, setCollections] = useState<SavedWebCollection[]>(() =>
    readWebCollections(localStorage.getItem(WEB_COLLECTIONS_KEY))
  );
  const [activeUrl, setActiveUrl] = useState<string | null>(() =>
    localStorage.getItem(WEB_LAST_COLLECTION_KEY)
  );

  async function addUrl(url: string, openAfter: boolean): Promise<boolean> {
    const loaded = manifests[url];
    if (!loaded) return false;
    const collection = {
      collectionId: loaded.collection_id,
      title: loaded.title,
      url,
      revision: loaded.revision,
      contentHash: loaded.content_hash,
    };
    setCollections((previous) => {
      const next = saveWebCollection(previous, collection);
      localStorage.setItem(WEB_COLLECTIONS_KEY, JSON.stringify(next));
      return next;
    });
    if (openAfter) {
      localStorage.setItem(WEB_LAST_COLLECTION_KEY, url);
      setActiveUrl(url);
    }
    return true;
  }

  return createElement(WebCollectionSettings, {
    activeCollectionId: collections.find((collection) => collection.url === activeUrl)
      ?.collectionId ?? null,
    busy: false,
    collections,
    error: null,
    openFeaturedPicker: false,
    onAddUrl: addUrl,
    onClose: () => undefined,
    onRemove: () => undefined,
    onSwitch: (collection) => {
      localStorage.setItem(WEB_LAST_COLLECTION_KEY, collection.url);
      setActiveUrl(collection.url);
    },
  });
}

async function addCollection(
  view: ReturnType<typeof render>,
  url: string,
  expectedCount: number,
  expectedTitle: string,
): Promise<void> {
  const input = view.getByRole("combobox", {
    name: "Collection URL or featured collection",
  });
  fireEvent.change(input, { target: { value: url } });
  fireEvent.click(view.getByRole("button", { name: "Add", exact: true }));
  await waitFor(() => assert.equal(
    view.container.querySelectorAll(".web-collection-entry").length,
    expectedCount,
  ));
  await waitFor(() => assert.match(view.container.textContent ?? "", new RegExp(expectedTitle)));
}

afterEach(() => {
  cleanup();
  delete globalThis.fetch;
});

after(() => dom.window.close());

test("Settings preserves distinct collections and reloads the persisted registry", async () => {
  const dom = installDom();
  const manifests = {
    [FIRST_URL]: manifest("first", "First collection", 1, "1"),
    [SECOND_URL]: manifest("second", "Second collection", 1, "2"),
  };
  let view = render(createElement(SettingsHarness, { manifests }), {
    container: dom.window.document.querySelector("#root")!,
  });

  await addCollection(view, FIRST_URL, 1, "First collection");
  await addCollection(view, SECOND_URL, 2, "Second collection");
  assert.equal(view.container.querySelectorAll(".web-collection-entry").length, 2);
  assert.match(view.container.textContent ?? "", /First collection/);
  assert.match(view.container.textContent ?? "", /Second collection/);
  assert.equal(view.container.querySelectorAll(".web-collection-entry.active").length, 1);

  view.unmount();
  dom.window.document.body.innerHTML = '<div id="root"></div>';
  view = render(createElement(SettingsHarness, { manifests }), {
    container: dom.window.document.querySelector("#root")!,
  });
  assert.equal(view.container.querySelectorAll(".web-collection-entry").length, 2);
  assert.match(view.container.textContent ?? "", /First collection/);
  assert.match(view.container.textContent ?? "", /Second collection/);
  assert.equal(view.container.querySelectorAll(".web-collection-entry.active").length, 1);
});

test("Settings updates a collection by collection_id without duplicating it", async () => {
  const dom = installDom();
  const manifests = {
    [FIRST_URL]: manifest("first", "First collection", 1, "1"),
    [SECOND_URL]: manifest("second", "Second collection", 1, "2"),
    [FIRST_UPDATE_URL]: manifest("first", "First collection updated", 2, "3"),
  };
  let view = render(createElement(SettingsHarness, { manifests }), {
    container: dom.window.document.querySelector("#root")!,
  });

  await addCollection(view, FIRST_URL, 1, "First collection");
  await addCollection(view, SECOND_URL, 2, "Second collection");
  await addCollection(view, FIRST_UPDATE_URL, 2, "First collection updated");
  const copy = view.container.textContent ?? "";
  assert.doesNotMatch(copy, new RegExp(FIRST_URL.replaceAll(".", "\\.")));
  assert.match(copy, /First collection updated/);
  assert.match(copy, /Second collection/);
  assert.equal(view.container.querySelectorAll(".web-collection-entry").length, 2);
  assert.equal(view.container.querySelectorAll(".web-collection-entry.active").length, 1);

  view.unmount();
  dom.window.document.body.innerHTML = '<div id="root"></div>';
  view = render(createElement(SettingsHarness, { manifests }), {
    container: dom.window.document.querySelector("#root")!,
  });
  assert.equal(view.container.querySelectorAll(".web-collection-entry").length, 2);
  assert.match(view.container.textContent ?? "", /First collection updated/);
  assert.match(view.container.textContent ?? "", /Second collection/);
  assert.equal(view.container.querySelectorAll(".web-collection-entry.active").length, 1);
});

test("featured picker hides collections already saved in the browser", async () => {
  const dom = installDom();
  const firstCollection: SavedWebCollection = {
    collectionId: "first",
    title: "First collection",
    url: FIRST_URL,
    revision: 1,
    contentHash: "1".repeat(64),
  };
  dom.window.localStorage.setItem(WEB_COLLECTIONS_KEY, JSON.stringify([firstCollection]));
  dom.window.localStorage.setItem(WEB_LAST_COLLECTION_KEY, FIRST_URL);
  globalThis.fetch = async () => new Response(JSON.stringify(featuredDirectory()), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  const view = render(createElement(SettingsHarness, {
    manifests: {
      [SECOND_URL]: manifest("second", "Second collection", 1, "2"),
    },
  }), {
    container: dom.window.document.querySelector("#root")!,
  });

  fireEvent.click(view.getByRole("button", { name: "Browse featured collections" }));
  await waitFor(() => assert.ok(
    view.getByRole("option", { name: /Second collection/ }),
  ));
  assert.equal(view.queryByRole("option", { name: /First collection/ }), null);

  fireEvent.click(view.getByRole("option", { name: /Second collection/ }));
  fireEvent.click(view.getByRole("button", { name: "Add", exact: true }));
  await waitFor(() => assert.equal(
    view.container.querySelectorAll(".web-collection-entry").length,
    2,
  ));

  fireEvent.click(view.getByRole("button", { name: "Browse featured collections" }));
  await waitFor(() => assert.ok(
    view.getByText("All featured collections are already installed."),
  ));
  assert.equal(view.queryAllByRole("option").length, 0);
});
