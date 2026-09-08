const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function transport(scenario = "success") {
  const context = {
    window: {},
    structuredClone,
    document: { getElementById: () => ({ value: scenario }) },
    fetch: () => {
      throw new Error("La démonstration ne doit jamais appeler le réseau");
    },
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "../app/static/demo.js"), "utf8"),
    context,
  );
  return context.window.createLockinDemo();
}
async function start(api, budget = 10) {
  return api("missions", {
    method: "POST",
    body: JSON.stringify({
      subject: "Sujet choisi",
      domains: ["example.com"],
      action_budget: budget,
      duration_minutes: 1,
    }),
  });
}
test("le succès démo contient un constat explicitement fictif et des traces associées", async () => {
  const api = transport();
  await start(api);
  let state;
  for (let i = 0; i < 6; i++) state = await api("missions/demo");
  assert.equal(state.status, "completed");
  assert.equal(state.findings.length, 1);
  assert.match(state.findings[0].summary, /ne provient pas/);
  const starts = state.events.filter((e) => e.kind === "action_started");
  const ends = state.events.filter((e) => e.kind === "action_finished");
  assert.equal(starts.length, 3);
  assert.equal(ends.length, 3);
  starts.forEach((e, i) =>
    assert.equal(e.data.action_number, ends[i].data.action_number),
  );
});
for (const [scenario, code] of [
  ["disabled", "tool_disabled_for_test"],
  ["error", "unavailable"],
]) {
  test(
    "la panne " + scenario + " reste visible et ne fabrique pas de résultat",
    async () => {
      const api = transport(scenario);
      await start(api);
      let state;
      for (let i = 0; i < 6; i++) state = await api("missions/demo");
      assert.equal(state.status, "failed");
      assert.equal(state.error, code);
      assert.equal(state.findings.length, 0);
      assert.ok(state.summary.partial);
      assert.ok(
        state.events.some(
          (e) => e.kind === "action_finished" && e.data.result.error === code,
        ),
      );
    },
  );
}
test("le budget ne peut pas être dépassé en démonstration", async () => {
  const api = transport();
  await start(api, 1);
  let state;
  for (let i = 0; i < 8; i++) state = await api("missions/demo");
  assert.equal(state.actions_used, 1);
  assert.equal(state.status, "budget_exhausted");
});
test("arrêter ferme l’action en cours et bloque la progression", async () => {
  const api = transport();
  await start(api);
  await api("missions/demo");
  const state = await api("missions/demo/stop", { method: "POST" });
  assert.equal(state.status, "stopped");
  assert.equal(state.current_action, null);
  assert.ok(state.events.some((e) => e.data.result?.error === "cancelled"));
  const next = await api("missions/demo");
  assert.equal(next.events.length, state.events.length);
});
