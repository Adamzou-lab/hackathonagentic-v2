const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
function reader() {
  const ctx = { window: {}, TextDecoder };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "../app/static/stream.js"), "utf8"),
    ctx,
  );
  return ctx.window.readLockinStream;
}
function response(text) {
  const bytes = new TextEncoder().encode(text);
  return {
    body: new ReadableStream({
      start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
        controller.close();
      },
    }),
  };
}
test("SSE conserve les accents et les trames découpées, ignore keepalive et accepte CRLF", async () => {
  const events = [];
  await reader()(
    response(
      ': keepalive\r\n\r\nevent: draft\r\ndata: {"text":"réponse"}\r\n\r\nevent: journal\ndata: {"seq":2,\ndata: "kind":"action_started"}\n\n',
    ),
    (kind, data) => events.push([kind, data]),
  );
  assert.equal(events.length, 2);
  assert.equal(events[0][1].text, "réponse");
  assert.equal(events[1][1].seq, 2);
});
test("end arrête le lecteur et ne traite pas les trames suivantes", async () => {
  const seen = [];
  await reader()(
    response(
      'event: end\ndata: {}\n\nevent: draft\ndata: {"text":"tardif"}\n\n',
    ),
    (kind) => {
      seen.push(kind);
      return false;
    },
  );
  assert.deepEqual(seen, ["end"]);
});
test("trame invalide provoque une erreur explicite", async () => {
  await assert.rejects(
    reader()(response("event: journal\ndata: invalid\n\n"), () => {}),
  );
});
