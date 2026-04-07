import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRoleRequestSequence } from "./useRoleRequestSequence";

describe("useRoleRequestSequence", () => {
  it("returns increasing tokens for the same role", () => {
    const { result } = renderHook(() => useRoleRequestSequence<"a" | "b">());

    let token1 = 0;
    let token2 = 0;
    let token3 = 0;
    act(() => {
      token1 = result.current.begin("a");
      token2 = result.current.begin("a");
      token3 = result.current.begin("a");
    });

    expect(token2).toBeGreaterThan(token1);
    expect(token3).toBeGreaterThan(token2);
  });

  it("isCurrent returns true only for the latest token of a role", () => {
    const { result } = renderHook(() => useRoleRequestSequence<"a">());

    let stale = 0;
    let fresh = 0;
    act(() => {
      stale = result.current.begin("a");
      fresh = result.current.begin("a");
    });

    expect(result.current.isCurrent("a", stale)).toBe(false);
    expect(result.current.isCurrent("a", fresh)).toBe(true);
  });

  it("tracks roles independently", () => {
    const { result } = renderHook(() => useRoleRequestSequence<"a" | "b">());

    let tokenA = 0;
    let tokenB = 0;
    act(() => {
      tokenA = result.current.begin("a");
      tokenB = result.current.begin("b");
    });

    // Bumping role b must NOT invalidate role a's token, and vice versa.
    let tokenB2 = 0;
    act(() => {
      tokenB2 = result.current.begin("b");
    });

    expect(result.current.isCurrent("a", tokenA)).toBe(true);
    expect(result.current.isCurrent("b", tokenB)).toBe(false);
    expect(result.current.isCurrent("b", tokenB2)).toBe(true);
  });

  it("reset clears the sequence for a single role", () => {
    const { result } = renderHook(() => useRoleRequestSequence<"a">());

    let token = 0;
    act(() => {
      token = result.current.begin("a");
      result.current.reset("a");
    });

    // After reset, the captured token is no longer the latest.
    expect(result.current.isCurrent("a", token)).toBe(false);
  });

  it("simulates the typical race: stale result discarded, fresh result kept", async () => {
    const { result } = renderHook(() => useRoleRequestSequence<"bom">());

    // Operation 1 begins, then operation 2 begins before op 1 resolves.
    let op1Token = 0;
    let op2Token = 0;
    act(() => {
      op1Token = result.current.begin("bom");
      op2Token = result.current.begin("bom");
    });

    // Op 1 finishes first chronologically (the slow file). Its token is
    // no longer current — caller should discard.
    expect(result.current.isCurrent("bom", op1Token)).toBe(false);

    // Op 2 finishes. Its token is current — caller should apply.
    expect(result.current.isCurrent("bom", op2Token)).toBe(true);
  });
});
