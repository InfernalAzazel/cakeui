/*! cakeui bridge 0.2.0 */
"use strict";
var cakeui = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // src/index.ts
  var index_exports = {};
  __export(index_exports, {
    CakeUIError: () => CakeUIError,
    emit: () => emit,
    invoke: () => invoke,
    isReady: () => isReady,
    listen: () => listen,
    off: () => off,
    once: () => once,
    ready: () => ready,
    version: () => version
  });
  var VERSION = "0.2.0";
  var CakeUIError = class extends Error {
    constructor(code, message, details) {
      super(message);
      this.name = "CakeUIError";
      this.code = code;
      this.details = details;
    }
  };
  var listeners = /* @__PURE__ */ new Map();
  var cachedBridge = null;
  var pendingBridge = null;
  function describe(error) {
    if (error instanceof Error) return error.message;
    return String(error);
  }
  function waitForBridge(timeoutMs) {
    const existing = typeof window !== "undefined" ? window.pywebview?.api : void 0;
    if (existing) {
      cachedBridge = existing;
      return Promise.resolve(existing);
    }
    if (timeoutMs <= 0) {
      return Promise.reject(
        new CakeUIError(
          "bridge_unavailable",
          "CakeUI is not running inside a CakeUI window, and no timeout was given."
        )
      );
    }
    return new Promise((resolve, reject) => {
      if (typeof window === "undefined") {
        reject(new CakeUIError("bridge_unavailable", "No `window` object: this is not a browser."));
        return;
      }
      let timer;
      const cleanup = () => {
        window.removeEventListener("pywebviewready", onReady);
        if (timer !== void 0) clearTimeout(timer);
      };
      const onReady = () => {
        cleanup();
        const api = window.pywebview?.api;
        if (!api) {
          reject(
            new CakeUIError(
              "bridge_unavailable",
              "`pywebviewready` fired but `window.pywebview.api` is missing."
            )
          );
          return;
        }
        cachedBridge = api;
        resolve(api);
      };
      window.addEventListener("pywebviewready", onReady, { once: true });
      timer = setTimeout(() => {
        cleanup();
        reject(
          new CakeUIError(
            "bridge_timeout",
            `The Python side did not answer within ${timeoutMs}ms. Is this page open in a CakeUI window?`
          )
        );
      }, timeoutMs);
    });
  }
  function getBridge(timeoutMs = 1e4) {
    if (cachedBridge) return Promise.resolve(cachedBridge);
    if (!pendingBridge) {
      pendingBridge = waitForBridge(timeoutMs).then(
        (bridge) => {
          pendingBridge = null;
          return bridge;
        },
        (error) => {
          pendingBridge = null;
          throw error;
        }
      );
    }
    return pendingBridge;
  }
  function parseEnvelope(raw) {
    if (typeof raw === "string") {
      try {
        return JSON.parse(raw);
      } catch {
        throw new CakeUIError("protocol_error", "The Python side returned malformed JSON.");
      }
    }
    if (raw && typeof raw === "object") return raw;
    throw new CakeUIError(
      "protocol_error",
      `The Python side returned ${raw === null ? "null" : typeof raw} instead of an envelope.`
    );
  }
  async function send(message, timeoutMs) {
    const bridge = await getBridge(timeoutMs);
    let payload;
    try {
      payload = JSON.stringify(message);
    } catch (error) {
      throw new CakeUIError("serialization_error", `Message is not JSON serializable: ${describe(error)}`);
    }
    let raw;
    try {
      raw = await bridge.dispatch(payload);
    } catch (error) {
      throw new CakeUIError("bridge_error", `Bridge call failed: ${describe(error)}`);
    }
    return parseEnvelope(raw);
  }
  async function invoke(command, args = {}) {
    const envelope = await send({ t: "invoke", cmd: command, args });
    if (!envelope.ok) {
      const error = envelope.error ?? {};
      throw new CakeUIError(
        error.code ?? "error",
        error.message ?? `Command "${command}" failed.`,
        error.details
      );
    }
    return envelope.data;
  }
  async function emit(event, payload) {
    const envelope = await send({ t: "emit", event, payload: payload ?? null });
    if (!envelope.ok) {
      const error = envelope.error ?? {};
      throw new CakeUIError(error.code ?? "error", error.message ?? `Event "${event}" failed.`, error.details);
    }
  }
  function listen(event, handler) {
    if (typeof event !== "string" || event.length === 0) {
      throw new TypeError("listen(event, handler): event must be a non-empty string.");
    }
    if (typeof handler !== "function") {
      throw new TypeError("listen(event, handler): handler must be a function.");
    }
    let bucket = listeners.get(event);
    if (!bucket) {
      bucket = /* @__PURE__ */ new Set();
      listeners.set(event, bucket);
    }
    bucket.add(handler);
    return () => off(event, handler);
  }
  function once(event, handler) {
    const wrapper = (payload) => {
      unlisten();
      handler(payload);
    };
    const unlisten = listen(event, wrapper);
    return unlisten;
  }
  function off(event, handler) {
    const bucket = listeners.get(event);
    if (!bucket) return;
    bucket.delete(handler);
    if (bucket.size === 0) listeners.delete(event);
  }
  function isReady() {
    return Boolean(cachedBridge || typeof window !== "undefined" && window.pywebview?.api);
  }
  async function ready(timeoutMs) {
    await getBridge(timeoutMs);
  }
  function dispatchEvent(event, payload) {
    let delivered = 0;
    for (const key of [event, "*"]) {
      const bucket = listeners.get(key);
      if (!bucket) continue;
      const arg = key === "*" ? { event, payload } : payload;
      for (const handler of Array.from(bucket)) {
        try {
          handler(arg);
          delivered += 1;
        } catch (error) {
          console.error(`[cakeui] listener for "${key}" threw:`, error);
        }
      }
    }
    return delivered;
  }
  function dispatchFromPython(rawJson) {
    let message;
    try {
      message = typeof rawJson === "string" ? JSON.parse(rawJson) : rawJson;
    } catch {
      console.error("[cakeui] Python sent an unparseable event payload:", rawJson);
      return 0;
    }
    if (!message || typeof message.event !== "string") {
      console.error("[cakeui] Python sent an event without a name:", rawJson);
      return 0;
    }
    return dispatchEvent(message.event, message.payload);
  }
  var internal = {
    version: VERSION,
    _dispatch: dispatchFromPython,
    invoke,
    emit,
    listen,
    once,
    off,
    ready,
    isReady
  };
  if (typeof window !== "undefined") {
    window.__cakeui = internal;
    const scope = window;
    if (!scope.cakeui) scope.cakeui = internal;
  }
  var version = VERSION;
  return __toCommonJS(index_exports);
})();
