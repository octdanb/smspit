/// <reference types="vitest/config" />
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";

// In dev the backend runs on 8825 (Caddy fronts everything on 8025); the
// proxy below keeps direct :5173 access working too.
const BACKEND = process.env.SMSPIT_BACKEND_URL ?? "http://localhost:8825";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, ws: true },
      "/2010-04-01": { target: BACKEND },
      "/v1": { target: BACKEND },
      "/v2": { target: BACKEND },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
