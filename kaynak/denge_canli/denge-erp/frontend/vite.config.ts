import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Oturum çerezi aynı köken üzerinden taşınsın diye API proxy'lenir.
      "/api": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
});
