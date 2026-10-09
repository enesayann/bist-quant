import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  envDir: webRoot,
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: { strict: true, allow: [webRoot] },
  },
  build: { chunkSizeWarningLimit: 700 },
});
