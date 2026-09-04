import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { createElement, useState } from "react";
import { JSDOM } from "jsdom";
import { upsertCollectionRegistration } from "@watchcraft/catalog-core";
import {
  CollectionSettings,
  type RegisteredCollection,
} from "./CollectionSettings.tsx";

const FIRST_URL = "https://collections.example/first/collection.json";
const SECOND_URL = "https://collections.example/second/collection.json";
const FIRST_UPDATE_URL = "https://mirror.example/first/collection.json";

const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", {
  url: "https://watchcraft.example/",
});
for (const [key, value] of Object.entries({
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  navigator: dom.window.navigator,
  window: dom.window,
  IS_REACT_ACT_ENVIRONMENT: true,
})) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value,
    writable: true,
  });
}
const { cleanup, fireEvent, render, waitFor } = await import("@testing-library/react");

const registrationsByUrl: Record<string, RegisteredCollection> = {
  [FIRST_URL]: registration("first", "First collection", 1, FIRST_URL),
  [SECOND_URL]: registration("second", "Second collection", 1, SECOND_URL),
  [FIRST_UPDATE_URL]: registration("first", "First collection updated", 2, FIRST_UPDATE_URL),
};

let persistedRegistry = "[]";

function registration(
  collectionId: string,
  title: string,
  revision: number,
  sourceLabel: string,
): RegisteredCollection {
  return {
    collectionId,
    title,
    revision,
    sourceType: "url",
    sourceLabel,
    active: false,
    archived: false,
    mediaRoot: null,
    mediaExpected: 0,
    mediaFound: 0,
    mediaExtra: 0,
    mediaModes: ["remote"],
  };
}

function SettingsHarness() {
  const [collections, setCollections] = useState<RegisteredCollection[]>(() =>
    JSON.parse(persistedRegistry) as RegisteredCollection[]
  );

  async function addUrl(url: string, openAfter: boolean): Promise<boolean> {
    const incoming = registrationsByUrl[url];
    if (!incoming) return false;
    setCollections((previous) => {
      const prepared = openAfter
        ? previous.map((collection) => ({ ...collection, active: false }))
        : previous;
      const next = upsertCollectionRegistration(prepared, {
        ...incoming,
        active: openAfter,
      });
      persistedRegistry = JSON.stringify(next);
      return next;
    });
    return true;
  }

  return createElement(CollectionSettings, {
    appVersion: "test",
    busy: false,
    collections,
    error: null,
    onAddFolder: async () => false,
    onAddUrl: addUrl,
    onClose: () => undefined,
    onLocateMedia: async () => undefined,
    onRemove: async () => undefined,
    onSetArchived: async () => undefined,
    onSwitch: async () => undefined,
    onUpdate: async () => undefined,
  });
}

async function addCollection(
  view: ReturnType<typeof render>,
  url: string,
  expectedCount: number,
  expectedTitle: string,
): Promise<void> {
  fireEvent.change(view.getByRole("combobox", {
    name: "Collection URL or featured collection",
  }), { target: { value: url } });
  fireEvent.click(view.getByRole("button", { name: "Add", exact: true }));
  await waitFor(() => assert.equal(
    view.container.querySelectorAll(".collection-entry").length,
    expectedCount,
  ));
  await waitFor(() => assert.match(view.container.textContent ?? "", new RegExp(expectedTitle)));
}

afterEach(() => {
  cleanup();
  delete globalThis.fetch;
  persistedRegistry = "[]";
});

after(() => dom.window.close());

test("desktop Settings preserves, updates, persists, and reloads collection registrations", async () => {
  dom.window.document.body.innerHTML = '<div id="root"></div>';
  globalThis.fetch = async () => new Response(JSON.stringify({ collections: [] }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  let view = render(createElement(SettingsHarness), {
    container: dom.window.document.querySelector("#root")!,
  });

  await addCollection(view, FIRST_URL, 1, "First collection");
  await addCollection(view, SECOND_URL, 2, "Second collection");
  await addCollection(view, FIRST_UPDATE_URL, 2, "First collection updated");
  const updatedCopy = view.container.textContent ?? "";
  assert.doesNotMatch(updatedCopy, new RegExp(FIRST_URL.replaceAll(".", "\\.")));
  assert.match(updatedCopy, new RegExp(FIRST_UPDATE_URL.replaceAll(".", "\\.")));
  assert.match(updatedCopy, /Second collection/);

  view.unmount();
  dom.window.document.body.innerHTML = '<div id="root"></div>';
  view = render(createElement(SettingsHarness), {
    container: dom.window.document.querySelector("#root")!,
  });
  assert.equal(view.container.querySelectorAll(".collection-entry").length, 2);
  assert.match(view.container.textContent ?? "", /First collection updated/);
  assert.match(view.container.textContent ?? "", /Second collection/);
  assert.equal(view.container.querySelectorAll(".active").length, 1);
});
