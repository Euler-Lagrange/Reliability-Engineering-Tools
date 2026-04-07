import { useCallback, useRef } from "react";

/**
 * Per-role monotonically-increasing request sequence for stale-safe async work.
 *
 * Each tool component fires multiple background operations against the same
 * file-input "role" (e.g., listSheets → inspectInput → analyzeTemplate). If
 * the user changes the input mid-flight, the older operation's result must
 * be discarded so it cannot overwrite newer state.
 *
 * Usage:
 *
 *     const sequence = useRoleRequestSequence<FileRole>();
 *
 *     async function handleBrowse(role: FileRole) {
 *       const token = sequence.begin(role);
 *       const result = await backendClient.listSheets(...);
 *       if (!sequence.isCurrent(role, token)) return;   // user moved on
 *       setSomething(result);
 *     }
 *
 * Tokens are simple integer counters; no special equality semantics are
 * required. Multiple roles are tracked independently, so a stale result on
 * role "bom" cannot block a fresh result on role "grouping".
 */
export function useRoleRequestSequence<RoleT extends string = string>() {
  const counters = useRef<Map<RoleT, number>>(new Map());

  const begin = useCallback((role: RoleT): number => {
    const next = (counters.current.get(role) ?? 0) + 1;
    counters.current.set(role, next);
    return next;
  }, []);

  const isCurrent = useCallback((role: RoleT, token: number): boolean => {
    return counters.current.get(role) === token;
  }, []);

  const reset = useCallback((role: RoleT): void => {
    counters.current.delete(role);
  }, []);

  return { begin, isCurrent, reset };
}
