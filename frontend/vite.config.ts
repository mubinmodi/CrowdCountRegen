import basicSsl from "@vitejs/plugin-basic-ssl";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

// `npm run dev:lan` serves over HTTPS on the LAN (self-signed), because phones only allow
// camera access on secure pages; needed to test browser publishing from a phone.
const lan = process.env.ZW_DEV_LAN === "1";

export default defineConfig({
  plugins: [react(), tailwindcss(), ...(lan ? [basicSsl()] : [])],
  server: {
    host: lan ? "0.0.0.0" : "localhost",
    // Same-origin proxy so the httpOnly session cookie works for fetch, <img> and WebSocket.
    proxy: {
      "/api": { target: backend, changeOrigin: true, ws: true },
    },
  },
});
