import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { createElement, useState } from "react";
import { JSDOM } from "jsdom";
import { CollectionSetup, needsCollectionSetup } from "./CollectionSetup.tsx";
import type { RegisteredCollection } from "./CollectionSettings.tsx";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://watchcraft.example/" });
for (const [key,value] of Object.entries({ window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, navigator: dom.window.navigator, IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis,key,{ configurable: true, value, writable: true });
const { render, fireEvent, cleanup, waitFor } = await import("@testing-library/react");
afterEach(cleanup); after(() => dom.window.close());
function collection(title = "Marc Adamus"): RegisteredCollection {
  return { collectionId: "test", title, revision: 1, sourceType: "url", sourceLabel: "https://example.com/collection.json", active: true, archived: false, mediaRoot: null, mediaExpected: 10, mediaFound: 0, mediaExtra: 0, mediaModes: ["referenced-local"], setupPending: true };
}

test("two collection-specific introductions and generic text remain plain presentation content", async () => {
  for (const title of ["Marc Adamus", "Photography Basics"]) {
    const c = collection(title); c.onboarding = { intro: `<b>Explore ${title}</b>`, media_folder_prompt: `Where is ${title}?`, media_folder_help: "Choose your course folder." };
    const view = render(createElement(CollectionSetup,{ collection:c, openAfter:true, onChooseFolder:async()=>null, onFinish:async()=>undefined, onCancel:()=>undefined }));
    assert.ok(view.getByRole("heading",{name:`Set up ${title}`})); assert.ok(view.getByText(`<b>Explore ${title}</b>`)); assert.equal(view.container.querySelector("b"),null);
    fireEvent.click(view.getByRole("button",{name:"Continue"})); assert.ok(view.getByRole("heading",{name:`Where is ${title}?`})); assert.ok(view.getByText("Choose your course folder.")); view.unmount();
  }
  const view = render(createElement(CollectionSetup,{ collection:collection(), openAfter:true, onChooseFolder:async()=>null, onFinish:async()=>undefined, onCancel:()=>undefined }));
  fireEvent.click(view.getByRole("button",{name:"Continue"})); assert.ok(view.getByText(/original subfolders/));
});

test("incorrect and cancelled folders can retry, partial matches can continue, and completion can retry", async () => {
  let attempts=0, finished=0;
  function Harness() {
    const [c,setC]=useState(collection());
    return createElement(CollectionSetup,{ collection:c, openAfter:true, onCancel:()=>undefined,
      onChooseFolder:async()=>{ attempts++; if(attempts===1) throw new Error("None of this collection’s videos were found. Choose another folder."); if(attempts===2) return null;
        const next={...c, mediaRoot:"/Volumes/Videos", mediaFound:6, mediaExtra:2}; setC(next); return next; },
      onFinish:async()=>{ finished++; if(finished===1) throw new Error("Drive unavailable. Reconnect it and retry."); } });
  }
  const view=render(createElement(Harness)); fireEvent.click(view.getByRole("button",{name:"Continue"}));
  fireEvent.click(view.getByRole("button",{name:"Choose video folder…"})); await view.findByRole("alert"); assert.equal(view.queryByRole("button",{name:/Start watching/}),null);
  fireEvent.click(view.getByRole("button",{name:"Choose video folder…"})); await view.findByText(/No folder selected/);
  fireEvent.click(view.getByRole("button",{name:"Choose video folder…"})); await view.findByText("6 of 10"); assert.ok(view.getByText(/4 videos are missing/)); assert.ok(view.getByText(/2 extra videos/));
  fireEvent.click(view.getByRole("button",{name:"Start watching available videos"})); await view.findByText(/Drive unavailable/);
  fireEvent.click(view.getByRole("button",{name:"Start watching available videos"})); await waitFor(()=>assert.equal(finished,2));
});

test("a full match reviews the current folder; finish-later and Escape are available", async () => {
  let cancelled=0, finished=0;
  const c={...collection(),mediaRoot:"/Videos",mediaFound:10};
  const view=render(createElement(CollectionSetup,{ collection:c, openAfter:false, initialStep:"folder",onChooseFolder:async()=>c,onFinish:async()=>{finished++;},onCancel:()=>{cancelled++;} }));
  fireEvent.click(view.getByRole("button",{name:"Review current folder"})); assert.ok(view.getByText(/All expected local videos/));
  fireEvent.click(view.getByRole("button",{name:"Save setup"})); await waitFor(()=>assert.equal(finished,1));
  fireEvent.keyDown(view.getByRole("dialog"),{key:"Escape"}); assert.equal(cancelled,1);
  fireEvent.click(view.getByRole("button",{name:"Finish later"})); assert.equal(cancelled,2);
});

test("configured, archived, and remote-only collections do not trigger first-run setup",()=>{
  assert.equal(needsCollectionSetup(collection()),true);
  assert.equal(needsCollectionSetup({...collection(),setupPending:false,mediaRoot:"/Videos"}),false);
  assert.equal(needsCollectionSetup({...collection(),mediaModes:["remote"]}),false);
  assert.equal(needsCollectionSetup({...collection(),archived:true}),false);
});
