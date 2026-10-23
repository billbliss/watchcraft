import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { createElement } from "react";
import { JSDOM } from "jsdom";
import { mockIPC, mockConvertFileSrc, clearMocks } from "@tauri-apps/api/mocks";
import type { RegisteredCollection } from "./CollectionSettings.tsx";
import { DesktopApp } from "./DesktopApp.tsx";

const dom=new JSDOM("<!doctype html><html><body></body></html>",{url:"https://watchcraft.example/"});
for(const [key,value] of Object.entries({window:dom.window,document:dom.window.document,navigator:dom.window.navigator,HTMLElement:dom.window.HTMLElement,localStorage:dom.window.localStorage,IS_REACT_ACT_ENVIRONMENT:true})) Object.defineProperty(globalThis,key,{configurable:true,value,writable:true});
const {render,fireEvent,cleanup,waitFor}=await import("@testing-library/react");
const originalFetch=globalThis.fetch;
afterEach(()=>{cleanup();clearMocks();localStorage.clear();globalThis.fetch=originalFetch;});after(()=>dom.window.close());
const url="https://example.com/course/collection.json";
const manifest={kind:"watchcraft.collection",schema_version:4,collection_id:"course",title:"Course",topic_scope:"collection",root:{type:"group",group_id:"root",title:"Course",children:[]},items:{},topics:{},topic_families:{},stats:{video_count:0,topic_count:0,topic_family_count:0},revision:1,content_hash:"0".repeat(64)};
function setupMock(options:{deepLink?:boolean;installed?:boolean;configured?:boolean;remote?:boolean}={}){
 let installed=options.installed??false;
 let c:RegisteredCollection={collectionId:"course",title:"Course",revision:1,sourceType:"url",sourceLabel:url,active:installed,archived:false,mediaRoot:options.configured?"/Videos":null,mediaExpected:options.remote?0:10,mediaFound:options.configured?10:0,mediaExtra:0,mediaModes:options.remote?["remote"]:["referenced-local"],setupPending:!options.remote&&!options.configured,onboarding:{intro:"Explore your local course."}};
 const calls:Array<{cmd:string;args:any}>=[];
 const fetches:string[]=[];
 const location=()=>({selectedRoot:null,collectionId:"course",manifestPath:"/private/course/manifest.json",metadataRoot:"/private/course",mediaRoot:c.mediaRoot,managedMediaRoot:null,mediaPathPrefix:"",mediaExpected:c.mediaExpected,mediaFound:c.mediaFound,mediaExtra:0});
 dom.window.confirm=()=>true;
 globalThis.fetch=async(input)=>{fetches.push(String(input));return new Response(JSON.stringify(String(input).includes("manifest.json")?manifest:{collections:[]}),{status:200,headers:{"Content-Type":"application/json"}});};
 mockConvertFileSrc("macos");
 mockIPC((cmd,args)=>{
  calls.push({cmd,args});
  if(cmd==="plugin:app|version")return "test";
  if(cmd==="diagnostics_snapshot")return {enabled:false,sessionId:"test",entries:[]};
  if(cmd==="load_current_collection")return installed?location():null;
  if(cmd==="youtube_bridge_base_url")return "https://watchcraft.stream/youtube-player/";
  if(cmd==="video_stream_base_url")return null;
  if(cmd==="plugin:deep-link|get_current")return options.deepLink?[`watchcraft://install?url=${encodeURIComponent(url)}`]:null;
  if(cmd==="list_registered_collections")return installed?[{...c}]:[];
  if(cmd==="install_collection_url"||cmd==="choose_collection_folder"){installed=true;c={...c,active:true,sourceType:cmd==="choose_collection_folder"?"folder":"url"};return location();}
  if(cmd==="choose_collection_media_folder"){c={...c,mediaRoot:"/Videos",mediaFound:6};return location();}
  if(cmd==="complete_collection_setup"){c={...c,setupPending:false};return location();}
  return null;
 },{shouldMockEvents:true});
 return {calls,fetches,collection:()=>c};
}

test("Settings URL and confirmed deep-link installs reach guided review and explicit completion",async()=>{
 for(const deepLink of [false,true]){
  const state=setupMock({deepLink}); const view=render(createElement(DesktopApp));
  if(!deepLink){fireEvent.click(await view.findByRole("button",{name:"Add from URL…"}));fireEvent.change(view.getByRole("combobox",{name:"Collection URL or featured collection"}),{target:{value:url}});fireEvent.click(view.getByRole("button",{name:"Add",exact:true}));}
  await view.findByRole("heading",{name:"Set up Course"}); assert.equal(state.calls.filter(c=>c.cmd==="choose_collection_media_folder").length,0);
  fireEvent.click(view.getByRole("button",{name:"Continue"}));fireEvent.click(view.getByRole("button",{name:"Choose video folder…"}));await view.findByText("6 of 10");assert.equal(state.collection().setupPending,true);
  assert.equal(state.fetches.filter(url=>url.includes("manifest.json")).length,0,"the player must not preload before setup completes");
  fireEvent.click(view.getByRole("button",{name:"Start watching available videos"}));await waitFor(()=>assert.equal(state.collection().setupPending,false));await waitFor(()=>assert.equal(view.queryByRole("dialog"),null));
  assert.deepEqual(state.calls.find(c=>c.cmd==="complete_collection_setup")?.args,{collectionId:"course",activate:true});view.unmount();clearMocks();
 }
});

test("folder imports get the same guided setup",async()=>{
 setupMock();const view=render(createElement(DesktopApp));fireEvent.click(await view.findByRole("button",{name:"Choose collection folder"}));await view.findByRole("heading",{name:"Set up Course"});
});

test("cancelled setup is resumable from Settings and after restart",async()=>{
 const state=setupMock({installed:true});let view=render(createElement(DesktopApp));await view.findByRole("heading",{name:"Set up Course"});fireEvent.click(view.getByRole("button",{name:"Finish later"}));
 fireEvent.click(await view.findByRole("button",{name:"Resume setup"}));await view.findByRole("heading",{name:"Set up Course"});assert.equal(state.collection().setupPending,true);
 view.unmount();view=render(createElement(DesktopApp));await view.findByRole("heading",{name:"Set up Course"});assert.equal(state.calls.filter(c=>c.cmd==="complete_collection_setup").length,0);
});

test("configured collections and remote-only installs bypass local setup",async()=>{
 for(const options of [{installed:true,configured:true},{deepLink:true,remote:true}]){
  const state=setupMock(options);const view=render(createElement(DesktopApp));await view.findByText("Course",{selector:".collection-name"});
  assert.equal(view.queryByRole("dialog"),null);assert.equal(state.calls.filter(c=>c.cmd==="choose_collection_media_folder").length,0);view.unmount();clearMocks();
 }
});
