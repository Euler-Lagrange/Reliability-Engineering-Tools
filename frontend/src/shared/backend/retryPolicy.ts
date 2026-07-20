/** Shared retry cadence for backend listeners and session reconnection. */
export const BACKEND_RETRY_DELAYS = [2_000, 4_000, 8_000, 15_000, 30_000] as const;
