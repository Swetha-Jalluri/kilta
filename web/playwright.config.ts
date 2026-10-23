import { defineConfig } from "@playwright/test";

// The browser tests only ever talk to the bridge started by serve_scripted.py, which replays the
// golden scenarios with a fake model. No real model, API key or Ollama is involved.
const BRIDGE = "http://127.0.0.1:8100";
const WEB = "http://localhost:5273";

export default defineConfig({
  testDir: "tests",
  timeout: 240_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  outputDir: "test-results/artifacts",
  use: { baseURL: WEB, browserName: "chromium", headless: true, trace: "off" },
  projects: [
    { name: "hd-1280x720-light", use: { viewport: { width: 1280, height: 720 }, colorScheme: "light" } },
    { name: "fhd-1920x1080-dark", use: { viewport: { width: 1920, height: 1080 }, colorScheme: "dark" } },
  ],
  webServer: [
    {
      command: "uv run --project ../bridge python ../bridge/scripts/serve_scripted.py",
      url: `${BRIDGE}/api/health`,
      timeout: 90_000,
      reuseExistingServer: false,
      env: { SCRIPTED_JSON: "tests/.generated/scenarios.json", SCRIPTED_WEB_ORIGINS: WEB },
    },
    {
      command: "npm run dev -- --port 5273",
      url: WEB,
      timeout: 60_000,
      reuseExistingServer: false,
      env: { VITE_BRIDGE_URL: BRIDGE },
    },
  ],
});
