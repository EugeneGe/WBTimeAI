// @wbtime/core · Result<T>：成功 / 失败判别，失败侧默认携带响应壳的失败形状。

import type { ErrorResponse } from "./envelope.js";

export interface OkResult<T> {
  readonly ok: true;
  readonly value: T;
}

export interface ErrResult<E = ErrorResponse> {
  readonly ok: false;
  readonly error: E;
}

export type Result<T, E = ErrorResponse> = OkResult<T> | ErrResult<E>;

export function ok<T>(value: T): OkResult<T> {
  return { ok: true, value };
}

export function err<E = ErrorResponse>(error: E): ErrResult<E> {
  return { ok: false, error };
}

export function isOk<T, E>(result: Result<T, E>): result is OkResult<T> {
  return result.ok;
}

export function isErr<T, E>(result: Result<T, E>): result is ErrResult<E> {
  return !result.ok;
}

/** 取值；失败侧抛错（调用方应先用 `isOk` 判别，此为兜底）。 */
export function unwrap<T, E>(result: Result<T, E>): T {
  if (result.ok) return result.value;
  throw new Error(`unwrap on ErrResult: ${JSON.stringify(result.error)}`);
}

/** 失败侧取默认值。 */
export function unwrapOr<T, E>(result: Result<T, E>, fallback: T): T {
  return result.ok ? result.value : fallback;
}
