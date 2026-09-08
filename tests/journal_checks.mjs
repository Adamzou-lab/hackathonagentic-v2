/* Verifications du journal de supervision. Aucun reseau, aucun appel API. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const J = createRequire(import.meta.url)("../app/static/journal.js");

let n = 0;
const test = (nom, fn) => { fn(); n++; console.log("  ok  " + nom); };

test("horodatage : date, heure, millisecondes et fuseau", () => {
  const s = J.stamp("2026-09-08T07:41:03.427Z");
  assert.ok(s.valid);
  assert.match(s.absolute, /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}\.\d{3} UTC[+-]\d{2}:\d{2}$/);
  assert.equal(s.iso, "2026-09-08T07:41:03.427Z");
});

test("horodatage : millisecondes conservees, pas arrondies", () => {
  assert.ok(J.stamp("2026-09-08T07:41:03.007Z").absolute.includes(".007"));
});

test("horodatage illisible signale sans planter", () => {
  const s = J.stamp("pas une date");
  assert.equal(s.valid, false);
  assert.equal(s.absolute, "Horodatage illisible");
});

test("temps ecoule conserve", () => {
  assert.equal(J.elapsed("2026-09-08T07:41:10Z", "2026-09-08T07:41:00Z"), 10);
  assert.equal(J.elapsed("bruit", "2026-09-08T07:41:00Z"), null);
});

test("diagnostic : dependance, cause et reaction pour un code connu", () => {
  const d = J.diagnose("document_redirect_rejected");
  assert.equal(d.dependency, "Site distant");
  assert.ok(d.cause && d.reaction && d.known);
});

test("diagnostic : code HTTP fournisseur reconnu dynamiquement", () => {
  const d = J.diagnose("anthropic_http_529");
  assert.equal(d.dependency, "Fournisseur");
  assert.ok(d.cause.includes("529"));
});

test("diagnostic : code inconnu signale comme tel, sans invention", () => {
  const d = J.diagnose("code_jamais_vu");
  assert.equal(d.known, false);
  assert.ok(d.cause.includes("code_jamais_vu"));
});

test("diagnostic : aucun code, aucun diagnostic", () => {
  assert.equal(J.diagnose(null), null);
});

test("code d'echec lu ou qu'il se trouve, y compris finished.error", () => {
  assert.equal(J.failureCode({ data: { code: "timeout" } }), "timeout");
  assert.equal(J.failureCode({ data: { result: { error: "blocked_url" } } }), "blocked_url");
  assert.equal(J.failureCode({ data: { status: "failed", error: "execution_error" } }), "execution_error");
  assert.equal(J.failureCode({ data: {} }), null);
});

test("quatre situations distinctes", () => {
  const cles = ["stopping", "stopped", "failed"].map((s) => J.situation(s, true).key);
  assert.deepEqual(cles, ["stop_requested", "stop_confirmed", "failed"]);
  assert.equal(J.situation("running", false).key, "connection_lost");
});

test("connexion perdue n'affirme jamais que l'agent est arrete", () => {
  const v = J.situation("running", false);
  assert.equal(v.source, "navigateur");
  assert.ok(/n'est pas arrêté/.test(v.detail));
  // Un arret confirme, lui, vient du serveur.
  assert.equal(J.situation("stopped", true).source, "serveur");
});

test("connexion perdue prime sur le dernier statut connu", () => {
  // Meme si le dernier etat recu disait 'running', l'ecran ne peut pas
  // pretendre suivre la mission pendant une coupure.
  assert.equal(J.situation("running", false).key, "connection_lost");
  assert.equal(J.situation("stopping", false).key, "connection_lost");
});

test("incident : horodate a la detection, avec la reserve explicite", () => {
  const i = J.incident("flux_interrompu", "coupure", "2026-09-08T07:41:03.427Z");
  assert.equal(i.origin, "navigateur");
  assert.equal(i.detected_at, "2026-09-08T07:41:03.427Z");
  assert.ok(/heure réelle de la coupure côté serveur est inconnue/i.test(i.note));
  assert.equal(i.seq, undefined, "un incident client ne doit pas porter de seq");
});

test("export : journal serveur et incidents client restent separes", () => {
  const mission = { id: "m1", subject: "sujet", events: [{ seq: 1, at: "x", kind: "created", data: {} }] };
  const inc = [J.incident("flux_interrompu", "coupure", "2026-09-08T07:41:03.427Z")];
  const out = J.buildExport(mission, inc, { simulated: false, now: "2026-09-08T08:00:00Z" });
  assert.equal(out.events.length, 1);
  assert.equal(out.client_incidents.length, 1);
  assert.ok(!out.events.some((e) => e.origin === "navigateur"), "incident melange au journal");
  assert.ok(/heure de détection|heures de détection/i.test(out.lecture));
  assert.equal(out.exported_at, "2026-09-08T08:00:00.000Z");
});

test("export : contrat du journal preserve (seq, at, kind, data)", () => {
  const e = { seq: 7, at: "2026-09-08T07:41:03.427Z", kind: "action_started", data: { tool: "read_page" } };
  const out = J.buildExport({ id: "m", subject: "s", events: [e] }, [], {});
  assert.deepEqual(Object.keys(out.events[0]).sort(), ["at", "data", "kind", "seq"]);
});

test("export sans mission ne plante pas", () => {
  const out = J.buildExport(null, [], {});
  assert.equal(out.mission_id, null);
  assert.deepEqual(out.events, []);
});

console.log(`\n${n} verifications passees.`);
