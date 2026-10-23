import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

const BRIDGE = "http://127.0.0.1:8100";
const SHOTS = "test-results/screens";

type Row = {
  text: string;
  member: "priya" | "lucia";
  language: string | null;
  states: (string | null)[];
  card_type?: string;
  tools: string[];
};
type Script = { name: string; connect_first: boolean; turns: Row[] };
const scripts: Record<string, Script> = JSON.parse(fs.readFileSync("tests/.generated/scenarios.json", "utf8"));

// A visible word from the withheld step: it must never reach the screen before the gate is open.
const HIDDEN = /sump|debris|sumidero/i;

async function settle(page: Page) {
  await expect(page.getByTestId("thinking")).toHaveCount(0);
  await expect(page.getByTestId("card")).toHaveCount(1); // the old card has finished fading out
  await page.waitForTimeout(650); // fade out, then fade in, before looking at the card
}

async function say(page: Page, row: Row, via: "type" | "start") {
  if (via === "start") {
    await Promise.all([page.waitForResponse((r) => r.url().includes("/api/turn")), page.getByTestId("start").click()]);
    return;
  }
  await page.getByTestId(`member-${row.member}`).click();
  const lang = row.language ?? (row.member === "lucia" ? "es" : "en");
  await page.getByTestId(`lang-${lang}`).click();
  const input = page.getByTestId("text-input");
  await input.fill(row.text);
  await Promise.all([page.waitForResponse((r) => r.url().includes("/api/turn")), input.press("Enter")]); // Enter sends
}

async function toolNames(page: Page): Promise<string[]> {
  return page.getByTestId("tool-row").evaluateAll((nodes) => nodes.map((n) => (n as HTMLElement).dataset.name ?? ""));
}

async function run(page: Page, name: "A" | "B" | "C", project: string) {
  const script = scripts[name];
  const seen = new Set<string>();
  const expectedTools: string[] = [];
  let shot = 0;

  await page.addInitScript(() => localStorage.setItem("kilta.mute", "1"));
  await page.request.post(`${BRIDGE}/api/reset`, { headers: { "X-Kilta-Demo": "1" } });
  await page.goto("/");
  await expect(page.getByTestId("wake-phrase")).toContainText("Hey Alexa, connect me to Kilta");
  if (name === "A") await page.screenshot({ path: `${SHOTS}/${project}/00-title.png` });

  if (!script.connect_first) {
    // The title screen's Start sends the connect line; B and C then continue from their own script.
    await say(page, script.turns[0], "start");
    await settle(page);
    expectedTools.push("get_household");
  }
  const rows = script.turns;
  for (const [index, row] of rows.entries()) {
    const viaStart = script.connect_first && index === 0;
    await say(page, row, viaStart ? "start" : "type");
    await settle(page);

    expectedTools.push(...row.tools);
    // The engine state badge is the real engine state, not something the page invents.
    const badge = (await page.getByTestId("engine-state").innerText()).trim();
    expect(row.states.map((s) => s ?? "NO REPAIR"), `state after "${row.text}"`).toContain(badge);

    const type = await page.getByTestId("card").getAttribute("data-card-type");
    if (row.card_type) expect(type, `card after "${row.text}"`).toBe(row.card_type);
    await expect(page.getByTestId("transcript")).toContainText(row.text.slice(0, 20));
    await expect.poll(async () => (await toolNames(page)).length, { message: "tool log fills" }).toBe(expectedTools.length);

    // A withheld step never shows its instruction, anywhere on the page.
    if ((await page.getByTestId("withheld").count()) > 0) {
      await expect(page.locator("body")).not.toContainText(HIDDEN);
      await expect(page.getByTestId("gate")).toBeVisible();
    }
    // "Next" without confirming: the engine refused it and the log says so.
    if (name === "A" && row.text === "Next.") {
      const refused = page.locator('[data-testid="tool-row"][data-name="next_step"][data-refused="1"]');
      await expect(refused).toHaveCount(1);
      await expect(page.getByTestId("gate")).toBeVisible();
    }

    const variant = await page.getByTestId("card").getAttribute("data-variant");
    const key = `${type ?? "none"}${variant && variant !== "open" ? `-${variant}` : ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      shot += 1;
      await page.screenshot({ path: `${SHOTS}/${project}/${name}-${String(shot).padStart(2, "0")}-${key}.png` });
    }
  }
  expect(await toolNames(page)).toEqual(expectedTools);
  return page;
}

test("scenario A by text: dishwasher E24, Priya then Lucia in Spanish", async ({ page }, info) => {
  await run(page, "A", info.project.name);
  // after the last turn: fixed card, health card, anonymous sharing done
  await expect(page.getByTestId("card")).toHaveAttribute("data-card-type", "insight_shared");
  await expect(page.getByTestId("mcp-status")).toContainText("2025-11-25");
});

test("scenario B: washer E31, renter handoff", async ({ page }, info) => {
  test.skip(info.project.name !== "hd-1280x720-light", "one viewport is enough for B");
  await run(page, "B", info.project.name);
  await expect(page.getByTestId("card")).toHaveAttribute("data-card-type", "landlord_message");
  await expect(page.getByTestId("card")).toContainText("Lakeview Property Management");
});

test("scenario C: danger stops everything", async ({ page }, info) => {
  await run(page, "C", info.project.name);
  await expect(page.getByTestId("card")).toHaveAttribute("data-card-type", "safety_stop");
  await expect(page.getByTestId("engine-state")).toHaveText("STOPPED");
});

test("Enter sends, reset clears the screen, the mic degrades quietly", async ({ page }, info) => {
  test.skip(info.project.name !== "hd-1280x720-light", "one viewport is enough");
  await page.addInitScript(() => localStorage.setItem("kilta.mute", "1"));
  await page.request.post(`${BRIDGE}/api/reset`, { headers: { "X-Kilta-Demo": "1" } });
  await page.goto("/");
  await page.getByTestId("start").click();
  await settle(page);
  await expect(page.getByTestId("card")).toHaveAttribute("data-card-type", "household");
  await page.getByTestId("reset").click();
  await expect(page.getByTestId("card-area")).toContainText("Hold the mic");
  await expect(page.getByTestId("engine-state")).toHaveText("NO REPAIR");
  await expect(page.getByTestId("transcript")).toContainText("Transcript");
});

test("spoken replies use an English voice for EN and a Spanish voice (es-ES, then es-MX) for ES", async ({ page }, info) => {
  test.skip(info.project.name !== "hd-1280x720-light", "one viewport is enough");
  await page.addInitScript(() => {
    const voices = [
      { name: "Alex", lang: "en-US" },
      { name: "Paulina", lang: "es-MX" },
      { name: "Monica", lang: "es-ES" },
    ];
    const spoken: { lang: string; voice: string | undefined; text: string }[] = [];
    // A plain utterance, so the stub voices above can be assigned to it.
    (window as any).SpeechSynthesisUtterance = class {
      lang = "";
      voice: { name: string } | null = null;
      rate = 1;
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    };
    (window as any).__spoken = spoken;
    Object.defineProperty(window, "speechSynthesis", {
      value: {
        getVoices: () => voices,
        cancel: () => {},
        speak: (u: any) => {
          spoken.push({ lang: u.lang, voice: u.voice?.name, text: u.text });
          u.onstart?.();
          setTimeout(() => u.onend?.(), 20);
        },
      },
    });
  });
  await page.request.post(`${BRIDGE}/api/reset`, { headers: { "X-Kilta-Demo": "1" } });
  await page.goto("/");
  await page.getByTestId("start").click(); // English: the connect line
  await settle(page);
  await page.getByTestId("member-lucia").click(); // Lucia speaks Spanish
  const input = page.getByTestId("text-input");
  await input.fill("My dishwasher is beeping and there's water at the bottom.");
  await Promise.all([page.waitForResponse((r) => r.url().includes("/api/turn")), input.press("Enter")]);
  await settle(page);
  const spoken = await page.evaluate(() => (window as any).__spoken);
  expect(spoken.map((s: any) => [s.lang, s.voice])).toEqual([
    ["en-US", "Alex"],
    ["es-ES", "Monica"], // es-ES is preferred over es-MX, and over any English voice
  ]);
});
