import { defineConfig } from "vitest/config";

// La carte est compilée dans le dossier servi par l'intégration.
export default defineConfig({
  build: {
    lib: {
      entry: "src/cospend-card.ts",
      formats: ["es"],
      fileName: () => "cospend-card.js",
    },
    outDir: "../../custom_components/cospend/www",
    emptyOutDir: false,
    sourcemap: false,
    target: "es2022",
  },
  test: {
    environment: "happy-dom",
    include: ["test/**/*.test.ts"],
  },
});
