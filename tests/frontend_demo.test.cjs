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
  assert.ok(state.last_request_cost.amount_usd > 0);
  assert.equal(state.last_request_cost.currency, "USD");
  assert.match(state.findings[0].summary, /ne provient pas/);
  const starts = state.events.filter((e) => e.kind === "action_started");
  const ends = state.events.filter((e) => e.kind === "action_finished");
  assert.equal(starts.length, 3);
  assert.equal(ends.length, 3);
  starts.forEach((e, i) =>
    assert.equal(e.data.action_number, ends[i].data.action_number),
  );
});
test("l’interface contient un affichage dédié au coût de la dernière requête", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../app/static/index.html"),
    "utf8",
  );
  const app = fs.readFileSync(
    path.join(__dirname, "../app/static/app.js"),
    "utf8",
  );
  assert.match(html, /id="lk-lastcost"/);
  assert.match(html, /COÛT DERNIÈRE REQUÊTE/);
  assert.match(app, /state\.last_request_cost/);
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

async function complete(api, state) {
  for (let i = 0; i < 6; i++) state = await api("missions/" + state.id);
  return state;
}
function createRequest(overrides = {}) {
  return {
    method: "POST",
    body: JSON.stringify({
      subject: "Veille des nouveautés",
      domains: [],
      auto_sources: true,
      action_budget: 10,
      duration_minutes: 5,
      ...overrides,
    }),
  };
}
test("les sources automatiques démo et leur caractère fictif sont visibles", async () => {
  const api = transport();
  const state = await api("missions", createRequest());
  assert.ok(state.domains.length > 0 && state.domains.length <= 5);
  assert.ok(
    state.events.some(
      (e) => e.kind === "sources_selected" && /fictifs/.test(e.data.reason),
    ),
  );
});
test("réutiliser une veille ne crée ni mission ni nouvelle trace", async () => {
  const api = transport();
  const first = await complete(api, await api("missions", createRequest()));
  const reused = await api("missions", createRequest());
  assert.equal(reused.id, first.id);
  assert.equal(reused.events.length, first.events.length);
  assert.equal(reused.reuse.reason, "recent_completed");
  const list = await api("watches?query=");
  assert.equal(list.total, 1);
  assert.equal(list.watches[0].run_count, 1);
});
test("actualiser enrichit la même veille et conserve le journal précédent", async () => {
  const api = transport();
  const first = await complete(api, await api("missions", createRequest()));
  const next = await complete(
    api,
    await api(
      "missions",
      createRequest({ watch_id: first.watch_id, force_refresh: true }),
    ),
  );
  assert.notEqual(next.id, first.id);
  assert.equal(next.watch_id, first.watch_id);
  assert.equal(next.new_findings_count, 1);
  const detail = await api("watches/" + first.watch_id);
  assert.equal(detail.findings.length, 2);
  assert.equal(detail.runs.length, 2);
  assert.equal(
    (await api("missions/" + first.id)).events.length,
    first.events.length,
  );
  const again = await complete(
    api,
    await api(
      "missions",
      createRequest({ watch_id: first.watch_id, force_refresh: true }),
    ),
  );
  assert.equal(again.new_findings_count, 0);
  assert.equal((await api("watches/" + first.watch_id)).findings.length, 2);
});
test("le rapprochement démo attend le choix explicite sans créer une recherche", async () => {
  const api = transport("similar");
  const first = await complete(api, await api("missions", createRequest()));
  const changed = createRequest({ subject: "Un autre sujet" });
  await assert.rejects(
    api("missions", changed),
    (error) => error.status === 409 && error.detail.code === "similar_watches",
  );
  assert.equal((await api("watches?query=")).total, 1);
  const linked = await complete(
    api,
    await api(
      "missions",
      createRequest({
        subject: "Un autre sujet",
        watch_id: first.watch_id,
        force_refresh: true,
      }),
    ),
  );
  assert.equal(linked.watch_id, first.watch_id);
  const separate = await api(
    "missions",
    createRequest({ subject: "Un troisième sujet", allow_new: true }),
  );
  assert.notEqual(separate.watch_id, first.watch_id);
  assert.equal((await api("watches?query=")).total, 2);
});
