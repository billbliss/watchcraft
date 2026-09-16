import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  base: "/portal/",
  build: {
    rollupOptions: {
      input: {
        portal: fileURLToPath(new URL("./index.html", import.meta.url)),
        submit: fileURLToPath(new URL("./submit/index.html", import.meta.url)),
        navigation: fileURLToPath(new URL("./src/navigation.tsx", import.meta.url)),
      },
      output: {
        entryFileNames: (chunk) => chunk.name === "navigation" ? "navigation.js" : "assets/[name]-[hash].js",
      },
    },
  },
});
