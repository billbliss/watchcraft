import { defineConfig } from "vite";

// Match directory redirects provided by the production static host.
export default defineConfig({
  appType: "mpa",
  plugins: [{
    name: "site-directory-redirects",
    configurePreviewServer(server) {
      server.middlewares.use((request, response, next) => {
        const url = new URL(request.url ?? "/", "http://localhost");
        if (["/portal", "/submit", "/app", "/gallery", "/youtube-player"].includes(url.pathname)) {
          response.writeHead(302, { Location: `${url.pathname}/${url.search}` });
          response.end();
          return;
        }
        next();
      });
    },
  }],
});
