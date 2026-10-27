import { describe, expect, it } from "vitest";
import { draftFrom, liftCredentials, toSourceInput } from "./SourceEditor";

describe("liftCredentials", () => {
  it("moves user:pass@ from a pasted URL into the fields", () => {
    const d = liftCredentials({ ...draftFrom(), source: "rtsp://admin:p%40ss@10.0.0.2:554/live" });
    expect(d.source).toBe("rtsp://10.0.0.2:554/live");
    expect(d.username).toBe("admin");
    expect(d.password).toBe("p@ss");
  });

  it("leaves URLs without credentials alone", () => {
    const d = { ...draftFrom(), source: "rtsp://10.0.0.2/live?user=a@b" };
    expect(liftCredentials(d)).toBe(d);
  });
});

describe("toSourceInput", () => {
  it("only sends a password when one was typed or cleared", () => {
    const base = { ...draftFrom(), source: "rtsp://cam/live", username: "u" };
    expect("password" in toSourceInput(base)).toBe(false);
    expect(toSourceInput({ ...base, password: "x" }).password).toBe("x");
    expect(toSourceInput({ ...base, clearPassword: true }).password).toBeNull();
  });

  it("sends no URL or credentials for browser cameras", () => {
    expect(toSourceInput({ ...draftFrom(), kind: "browser", source: "junk", username: "u" })).toEqual({
      kind: "browser",
      options: {},
    });
  });
});
