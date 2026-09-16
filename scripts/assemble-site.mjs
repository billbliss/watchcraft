import { cp, mkdir, writeFile, rm } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const output = new URL("dist/", root);
await rm(output, { recursive: true, force: true });
await mkdir(new URL("assets/", output), { recursive: true });
for (const path of ["index.html", "gallery.html", "app.js", "directory.mjs", "gallery", "youtube-player"]) {
  await cp(new URL(`site/${path}`, root), new URL(path, output), { recursive: true });
}
await cp(new URL("apps/web/dist/", root), new URL("app/", output), { recursive: true });
await cp(new URL("apps/portal/dist/", root), new URL("portal/", output), { recursive: true });
await cp(new URL("apps/portal/dist/submit/", root), new URL("submit/", output), { recursive: true });
await cp(new URL("apps/desktop/src-tauri/icons/128x128.png", root), new URL("assets/watchcraft.png", output));
await writeFile(new URL(".nojekyll", output), "");
console.log("Website assembled in dist/.");
