import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BUSY_RETRY_MS, VideoGate } from "./video";

describe("VideoGate", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("pauses after the idle timeout and resumes on input", () => {
    const gate = new VideoGate();
    gate.setIdleTimeout(600);
    vi.advanceTimersByTime(599_000);
    expect(gate.state).toBeNull();
    vi.advanceTimersByTime(1_000);
    expect(gate.state).toBe("idle");
    gate.activity();
    expect(gate.state).toBeNull();
  });

  it("input keeps pushing the idle pause back", () => {
    const gate = new VideoGate();
    gate.setIdleTimeout(10);
    vi.advanceTimersByTime(9_000);
    gate.activity();
    vi.advanceTimersByTime(9_000);
    expect(gate.state).toBeNull();
  });

  it("never idles without a timeout", () => {
    const gate = new VideoGate();
    gate.setIdleTimeout(null);
    vi.advanceTimersByTime(24 * 3600_000);
    expect(gate.state).toBeNull();
  });

  it("pauses while hidden and resumes when visible", () => {
    const gate = new VideoGate();
    gate.setHidden(true);
    expect(gate.state).toBe("hidden");
    gate.setHidden(false);
    expect(gate.state).toBeNull();
  });

  it("retries by itself after being busy", () => {
    const gate = new VideoGate();
    gate.busy();
    vi.advanceTimersByTime(BUSY_RETRY_MS - 1);
    expect(gate.state).toBe("busy");
    vi.advanceTimersByTime(1);
    expect(gate.state).toBeNull();
  });

  it("an expired session stays paused until the viewer resumes, even with input", () => {
    const gate = new VideoGate();
    gate.setIdleTimeout(600);
    gate.expired();
    gate.activity();
    gate.setHidden(true);
    gate.setHidden(false);
    expect(gate.state).toBe("expired");
    gate.resume();
    expect(gate.state).toBeNull();
  });

  it("notifies subscribers only on changes", () => {
    const gate = new VideoGate();
    const seen: unknown[] = [];
    gate.subscribe(() => seen.push(gate.state));
    gate.setHidden(true);
    gate.setHidden(true);
    gate.setHidden(false);
    expect(seen).toEqual(["hidden", null]);
  });
});
