import { defineConfig, loadEnv, transformWithEsbuild } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env vars with REACT_APP_ prefix (backward-compat with CRA)
  const env = loadEnv(mode, process.cwd(), "REACT_APP_");

  return {
    plugins: [
      // Must come BEFORE the react plugin so vite:import-analysis
      // never sees raw JSX syntax inside .js files.
      {
        name: "treat-js-files-as-jsx",
        async transform(code, id) {
          if (!id.match(/src\/.*\.js$/)) return null;
          return transformWithEsbuild(code, id, { loader: "jsx" });
        },
      },
      react(),
    ],
    // Expose REACT_APP_* as process.env.REACT_APP_* so existing code
    // in context.js doesn't need to change.
    define: Object.fromEntries(
      Object.entries(env).map(([key, value]) => [
        `process.env.${key}`,
        JSON.stringify(value),
      ])
    ),
    optimizeDeps: {
      esbuildOptions: {
        loader: { ".js": "jsx" },
      },
    },
    // public/ contains only the CRA index.html template — skip it
    // so it doesn't conflict with the root index.html Vite uses.
    publicDir: false,
    server: {
      port: 3000,
    },
  };
});
