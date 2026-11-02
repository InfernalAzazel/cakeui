// 占位类型声明 —— 仅供模板自己在仓库里通过类型检查。
//
// `cakeui new` 会在写完模板之后再生成真正的 cakeui.js / cakeui.d.ts，把本文件
// 覆盖掉（见 scaffold.py：先 _merge，再 ensure_bridge_module）。所以这里只需要
// 覆盖 cakeui-boot.ts 实际用到的那几个符号。
export declare class CakeUIError extends Error {
  readonly code: string;
  readonly details?: unknown;
}

export declare function invoke<TResult = unknown>(
  command: string,
  args?: Record<string, unknown>,
): Promise<TResult>;

export declare function listen<T = unknown>(
  event: string,
  handler: (payload: T) => void,
): () => void;
