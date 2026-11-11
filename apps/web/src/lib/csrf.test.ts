import { describe, expect, it } from "vitest";
import { isTrustedWrite } from "./csrf";

describe("isTrustedWrite", () => {
  it("allows reads from anywhere (the API still requires a session)", () => {
    expect(isTrustedWrite("GET", "https://attacker.example", "localhost:3000", "cross-site")).toBe(true);
  });

  it("allows writes from the app's own pages", () => {
    expect(isTrustedWrite("POST", "http://localhost:3000", "localhost:3000", "same-origin")).toBe(true);
    expect(isTrustedWrite("delete", "http://localhost:3000", "localhost:3000", "same-origin")).toBe(true);
  });

  it("refuses writes from other sites, including other local servers", () => {
    expect(isTrustedWrite("POST", "https://attacker.example", "localhost:3000", "cross-site")).toBe(false);
    expect(isTrustedWrite("POST", "http://localhost:5173", "localhost:3000", "same-site")).toBe(false);
    expect(isTrustedWrite("PATCH", "null", "localhost:3000", "cross-site")).toBe(false);
  });

  it("refuses browser writes without Origin unless same-origin", () => {
    expect(isTrustedWrite("POST", null, "localhost:3000", "cross-site")).toBe(false);
    expect(isTrustedWrite("POST", null, "localhost:3000", "same-site")).toBe(false);
    expect(isTrustedWrite("POST", null, "localhost:3000", "same-origin")).toBe(true);
  });

  it("allows non-browser clients that send neither header", () => {
    expect(isTrustedWrite("POST", null, "localhost:3000", null)).toBe(true);
  });
});
