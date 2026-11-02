/**
 * CakeUI frontend API.
 *
 * The bridge talks to the Python side over pywebview's `js_api` channel using a
 * small JSON envelope protocol. This module is the single source of truth for
 * that protocol: the Python package ships the built copy of this file, so the
 * bundled bridge and the npm package can never drift apart.
 */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | {
    [key: string]: JsonValue;
};
export interface CakeUIErrorPayload {
    code?: string;
    message?: string;
    details?: unknown;
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
export declare class CakeUIError extends Error {
    readonly code: string;
    readonly details?: unknown;
    constructor(code: string, message: string, details?: unknown);
}
export type Listener<T = unknown> = (payload: T) => void;
export type Unlisten = () => void;
/**
 * Call a Python command registered with `@app.command`.
 *
 * @example
 * const greeting = await invoke<string>("greet", { name: "Ada" });
 */
export declare function invoke<TResult = unknown>(command: string, args?: Record<string, unknown>): Promise<TResult>;
/**
 * Send an event to Python (received by `@app.on(...)` handlers).
 *
 * Chain `.catch()` or await it: the promise rejects when Python raises.
 */
export declare function emit(event: string, payload?: unknown): Promise<void>;
/**
 * Listen for an event emitted by Python via `app.emit(...)`.
 *
 * Returns an unsubscribe function. `listen("*", ...)` receives every event as
 * `{ event, payload }`, which is handy for logging.
 */
export declare function listen<T = unknown>(event: string, handler: Listener<T>): Unlisten;
/** Listen for a single occurrence of `event`. */
export declare function once<T = unknown>(event: string, handler: Listener<T>): Unlisten;
/** Remove a previously registered listener. */
export declare function off<T = unknown>(event: string, handler: Listener<T>): void;
/** True once `window.pywebview.api` exists. */
export declare function isReady(): boolean;
/** Wait until the Python bridge can accept calls. */
export declare function ready(timeoutMs?: number): Promise<void>;
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
export declare const version = "0.1.0";
export {};
