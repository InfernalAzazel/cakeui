/**
 * CakeUI frontend API.
 *
 * The bridge talks to the Python side over pywebview's `js_api` channel using a
 * small JSON envelope protocol. This module is the single source of truth for
 * that protocol: the Python package ships the built copy of this file, so the
 * bundled bridge and the npm package can never drift apart.
 */

const VERSION = "0.2.0";

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export interface CakeUIErrorPayload {
  code?: string;
  message?: string;
  details?: unknown;
}

interface Envelope {
  ok: boolean;
  data?: unknown;
  error?: CakeUIErrorPayload;
}

interface PywebviewBridge {
  dispatch(payload: string): Promise<string>;
}

interface PywebviewGlobal {
  api?: PywebviewBridge;
}

declare global {
  interface Window {
    pywebview?: PywebviewGlobal;
    __cakeui?: CakeUIInternalApi;
  }
}

/** A command failed on the Python side. Branch on `code`, not on `message`. */
export class CakeUIError extends Error {
  readonly code: string;
  readonly details?: unknown;

  constructor(code: string, message: string, details?: unknown) {
    super(message);
    this.name = "CakeUIError";
    this.code = code;
    this.details = details;
  }
}

export type Listener<T = unknown> = (payload: T) => void;
export type Unlisten = () => void;

const listeners = new Map<string, Set<Listener<any>>>();

let cachedBridge: PywebviewBridge | null = null;
let pendingBridge: Promise<PywebviewBridge> | null = null;

function describe(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function waitForBridge(timeoutMs: number): Promise<PywebviewBridge> {
  const existing = typeof window !== "undefined" ? window.pywebview?.api : undefined;
  if (existing) {
    cachedBridge = existing;
    return Promise.resolve(existing);
  }
  if (timeoutMs <= 0) {
    return Promise.reject(
      new CakeUIError(
        "bridge_unavailable",
        "CakeUI is not running inside a CakeUI window, and no timeout was given.",
      ),
    );
  }

  return new Promise<PywebviewBridge>((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new CakeUIError("bridge_unavailable", "No `window` object: this is not a browser."));
      return;
    }

    let timer: ReturnType<typeof setTimeout> | undefined;
    const cleanup = (): void => {
      window.removeEventListener("pywebviewready", onReady);
      if (timer !== undefined) clearTimeout(timer);
    };
    const onReady = (): void => {
      cleanup();
      const api = window.pywebview?.api;
      if (!api) {
        reject(
          new CakeUIError(
            "bridge_unavailable",
            "`pywebviewready` fired but `window.pywebview.api` is missing.",
          ),
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
          `The Python side did not answer within ${timeoutMs}ms. ` +
            "Is this page open in a CakeUI window?",
        ),
      );
    }, timeoutMs);
  });
}

/** Resolve the bridge, waiting for `pywebviewready` if needed. */
function getBridge(timeoutMs = 10_000): Promise<PywebviewBridge> {
  if (cachedBridge) return Promise.resolve(cachedBridge);
  if (!pendingBridge) {
    pendingBridge = waitForBridge(timeoutMs).then(
      (bridge) => {
        pendingBridge = null;
        return bridge;
      },
      (error) => {
        pendingBridge = null; // never cache a failure: a later call may still work
        throw error;
      },
    );
  }
  return pendingBridge;
}

function parseEnvelope(raw: unknown): Envelope {
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as Envelope;
    } catch {
      throw new CakeUIError("protocol_error", "The Python side returned malformed JSON.");
    }
  }
  if (raw && typeof raw === "object") return raw as Envelope;
  throw new CakeUIError(
    "protocol_error",
    `The Python side returned ${raw === null ? "null" : typeof raw} instead of an envelope.`,
  );
}

async function send(message: Record<string, unknown>, timeoutMs?: number): Promise<Envelope> {
  const bridge = await getBridge(timeoutMs);
  let payload: string;
  try {
    payload = JSON.stringify(message);
  } catch (error) {
    throw new CakeUIError("serialization_error", `Message is not JSON serializable: ${describe(error)}`);
  }

  let raw: string;
  try {
    raw = await bridge.dispatch(payload);
  } catch (error) {
    throw new CakeUIError("bridge_error", `Bridge call failed: ${describe(error)}`);
  }
  return parseEnvelope(raw);
}

/**
 * Call a Python command registered with `@app.command`.
 *
 * @example
 * const greeting = await invoke<string>("greet", { name: "Ada" });
 */
export async function invoke<TResult = unknown>(
  command: string,
  args: Record<string, unknown> = {},
): Promise<TResult> {
  const envelope = await send({ t: "invoke", cmd: command, args });
  if (!envelope.ok) {
    const error = envelope.error ?? {};
    throw new CakeUIError(
      error.code ?? "error",
      error.message ?? `Command "${command}" failed.`,
      error.details,
    );
  }
  return envelope.data as TResult;
}

/**
 * Send an event to Python (received by `@app.on(...)` handlers).
 *
 * Chain `.catch()` or await it: the promise rejects when Python raises.
 */
export async function emit(event: string, payload?: unknown): Promise<void> {
  const envelope = await send({ t: "emit", event, payload: payload ?? null });
  if (!envelope.ok) {
    const error = envelope.error ?? {};
    throw new CakeUIError(error.code ?? "error", error.message ?? `Event "${event}" failed.`, error.details);
  }
}

/**
 * Listen for an event emitted by Python via `app.emit(...)`.
 *
 * Returns an unsubscribe function. `listen("*", ...)` receives every event as
 * `{ event, payload }`, which is handy for logging.
 */
export function listen<T = unknown>(event: string, handler: Listener<T>): Unlisten {
  if (typeof event !== "string" || event.length === 0) {
    throw new TypeError("listen(event, handler): event must be a non-empty string.");
  }
  if (typeof handler !== "function") {
    throw new TypeError("listen(event, handler): handler must be a function.");
  }
  let bucket = listeners.get(event);
  if (!bucket) {
    bucket = new Set();
    listeners.set(event, bucket);
  }
  bucket.add(handler as Listener<any>);
  return () => off(event, handler);
}

/** Listen for a single occurrence of `event`. */
export function once<T = unknown>(event: string, handler: Listener<T>): Unlisten {
  const wrapper: Listener<T> = (payload) => {
    unlisten();
    handler(payload);
  };
  const unlisten = listen(event, wrapper);
  return unlisten;
}

/** Remove a previously registered listener. */
export function off<T = unknown>(event: string, handler: Listener<T>): void {
  const bucket = listeners.get(event);
  if (!bucket) return;
  bucket.delete(handler as Listener<any>);
  if (bucket.size === 0) listeners.delete(event);
}

/** True once `window.pywebview.api` exists. */
export function isReady(): boolean {
  return Boolean(cachedBridge || (typeof window !== "undefined" && window.pywebview?.api));
}

/** Wait until the Python bridge can accept calls. */
export async function ready(timeoutMs?: number): Promise<void> {
  await getBridge(timeoutMs);
}

function dispatchEvent(event: string, payload: unknown): number {
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
        // One bad listener must not stop the others or break the Python caller.
        console.error(`[cakeui] listener for "${key}" threw:`, error);
      }
    }
  }
  return delivered;
}

/** Called by the Python side through `evaluate_js`; not part of the public API. */
function dispatchFromPython(rawJson: string): number {
  let message: { event?: unknown; payload?: unknown };
  try {
    message = typeof rawJson === "string" ? JSON.parse(rawJson) : (rawJson as typeof message);
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

interface CakeUIInternalApi {
  version: string;
  _dispatch: (rawJson: string) => number;
  invoke: typeof invoke;
  emit: typeof emit;
  listen: typeof listen;
  once: typeof once;
  off: typeof off;
  ready: typeof ready;
  isReady: typeof isReady;
}

const internal: CakeUIInternalApi = {
  version: VERSION,
  _dispatch: dispatchFromPython,
  invoke,
  emit,
  listen,
  once,
  off,
  ready,
  isReady,
};

if (typeof window !== "undefined") {
  window.__cakeui = internal;
  // The IIFE build assigns `window.cakeui` after this module body runs; a bundler
  // build (import ... from "cakeui") would otherwise leave the global unset.
  const scope = window as unknown as { cakeui?: CakeUIInternalApi };
  if (!scope.cakeui) scope.cakeui = internal;
}

export const version = VERSION;
