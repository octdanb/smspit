import { beforeEach, describe, expect, it } from "vitest";

import { applyTheme, initialTheme } from "./theme";

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  it("applies and persists dark mode", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(initialTheme()).toBe("dark");
  });

  it("clears dark mode when switching back to light", () => {
    applyTheme("dark");
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(initialTheme()).toBe("light");
  });
});
