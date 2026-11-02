/**
 * Tests for the built bundle, against a fake pywebview bridge.
 * Run with `npm test` (or `npm test -- --test-reporter=spec`).
 */
import assert from "node:assert/strict";
import test from "node:test";

const sent = [];
let respond = (message) => JSON.stringify({ ok: true, data: null });

globalThis.window = {
  addEventListener() {},
  removeEventListener() {},
  pywebview: {
    api: {
      async dispatch(payload) {
        const message = JSON.parse(payload);
        sent.push(message);
        return respond(message);
      },
    },
  },
};

const { invoke, listen, emit, once, isReady, ready, CakeUIError, version } = await import(
  "../dist/index.mjs"
);

test("the module exposes itself for the Python side", () => {
  assert.equal(typeof window.__cakeui._dispatch, "function");
  assert.equal(window.__cakeui.version, version);
});

test("isReady and ready() resolve immediately when the bridge exists", async () => {
  assert.equal(isReady(), true);
  await ready(50);
});

test("invoke sends an envelope and unwraps the result", async () => {
  sent.length = 0;
  respond = () => JSON.stringify({ ok: true, data: { message: "hello" } });

  const result = await invoke("greet", { name: "Ada" });

  assert.deepEqual(result, { message: "hello" });
  assert.deepEqual(sent[0], { t: "invoke", cmd: "greet", args: { name: "Ada" } });
});

test("invoke maps a failed envelope to a typed error", async () => {
  respond = () =>
    JSON.stringify({
      ok: false,
      error: { code: "validation_error", message: "nope", details: [{ loc: ["name"] }] },
    });

  await assert.rejects(
    () => invoke("greet", {}),
    (error) => {
      assert.ok(error instanceof CakeUIError);
      assert.equal(error.name, "CakeUIError");
      assert.equal(error.code, "validation_error");
      assert.deepEqual(error.details, [{ loc: ["name"] }]);
      return true;
    },
  );
});

test("a malformed response is reported as a protocol error", async () => {
  respond = () => "not json";
  await assert.rejects(() => invoke("greet"), { code: "protocol_error" });
});

test("emit sends an event envelope", async () => {
  sent.length = 0;
  respond = () => JSON.stringify({ ok: true, data: 1 });

  await emit("log", { message: "hi" });

  assert.deepEqual(sent[0], { t: "emit", event: "log", payload: { message: "hi" } });
});

test("emit surfaces Python-side handler failures", async () => {
  respond = () =>
    JSON.stringify({ ok: false, error: { code: "event_handler_error", message: "boom" } });
  await assert.rejects(() => emit("log"), { code: "event_handler_error" });
});

test("unserializable arguments are rejected before hitting the bridge", async () => {
  const circular = {};
  circular.self = circular;
  await assert.rejects(() => invoke("greet", { circular }), { code: "serialization_error" });
});

test("listen receives events dispatched from Python", () => {
  const seen = [];
  const unlisten = listen("toast", (payload) => seen.push(payload));

  window.__cakeui._dispatch(JSON.stringify({ event: "toast", payload: { text: "one" } }));
  window.__cakeui._dispatch(JSON.stringify({ event: "other", payload: { text: "two" } }));
  assert.deepEqual(seen, [{ text: "one" }]);

  unlisten();
  window.__cakeui._dispatch(JSON.stringify({ event: "toast", payload: { text: "three" } }));
  assert.deepEqual(seen, [{ text: "one" }]);
});

test("the wildcard listener sees every event", () => {
  const seen = [];
  const unlisten = listen("*", (message) => seen.push(message));

  window.__cakeui._dispatch(JSON.stringify({ event: "a", payload: 1 }));
  window.__cakeui._dispatch(JSON.stringify({ event: "b", payload: 2 }));
  unlisten();

  assert.deepEqual(seen, [
    { event: "a", payload: 1 },
    { event: "b", payload: 2 },
  ]);
});

test("once() unsubscribes after the first event", () => {
  const seen = [];
  once("ping", (payload) => seen.push(payload));

  window.__cakeui._dispatch(JSON.stringify({ event: "ping", payload: 1 }));
  window.__cakeui._dispatch(JSON.stringify({ event: "ping", payload: 2 }));

  assert.deepEqual(seen, [1]);
});

test("a throwing listener does not break delivery to others", () => {
  const seen = [];
  const noisy = () => {
    throw new Error("listener bug");
  };
  const unlistenNoisy = listen("crash", noisy);
  const unlistenGood = listen("crash", (payload) => seen.push(payload));

  const originalError = console.error;
  console.error = () => {};
  try {
    const delivered = window.__cakeui._dispatch(JSON.stringify({ event: "crash", payload: 1 }));
    assert.equal(delivered, 1);
  } finally {
    console.error = originalError;
    unlistenNoisy();
    unlistenGood();
  }

  assert.deepEqual(seen, [1]);
});

test("garbage from Python is ignored instead of throwing", () => {
  assert.equal(window.__cakeui._dispatch("not json"), 0);
  assert.equal(window.__cakeui._dispatch(JSON.stringify({ payload: 1 })), 0);
});
