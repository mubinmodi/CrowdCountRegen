import { describe, expect, it } from "vitest";
import { hitTest, toNormalized } from "./zone";

const rect = { left: 100, top: 50, width: 400, height: 200 };

describe("toNormalized", () => {
  it("maps pointer position into [0, 1] image space", () => {
    expect(toNormalized(300, 150, rect)).toEqual([0.5, 0.5]);
    expect(toNormalized(100, 50, rect)).toEqual([0, 0]);
  });

  it("clamps positions outside the image", () => {
    expect(toNormalized(0, 1000, rect)).toEqual([0, 1]);
  });
});

describe("hitTest", () => {
  it("finds the closest point within the radius", () => {
    const pts: [number, number][] = [
      [0.1, 0.1],
      [0.12, 0.1],
      [0.9, 0.9],
    ];
    expect(hitTest(pts, [0.119, 0.1])).toBe(1);
    expect(hitTest(pts, [0.5, 0.5])).toBe(-1);
  });
});
