import { describe, expect, it } from "vitest";
import { applicationStatusLabel, skillStatusLabel, undocumentedMeansMissing } from "./labels";
import { postedLabel, salaryLabel, stripMarkup } from "./format";

describe("skill status language", () => {
  it("does not describe an undocumented skill as missing", () => {
    expect(skillStatusLabel("unverified")).toBe("Not on your profile yet");
    expect(skillStatusLabel("unverified").toLowerCase()).not.toContain("missing");
    expect(undocumentedMeansMissing("unverified")).toBe(false);
    expect(undocumentedMeansMissing("not_possessed")).toBe(true);
  });

  it("labels application stages in plain language", () => {
    expect(applicationStatusLabel("manual_action_required")).toBe("Finish on employer site");
    expect(applicationStatusLabel("awaiting_skill_verification")).toBe("Needs your answers");
  });
});

describe("formatting", () => {
  it("formats posting age and salary", () => {
    expect(postedLabel(0)).toBe("Posted today");
    expect(postedLabel(9)).toBe("Posted 9d ago");
    expect(salaryLabel(44500, 71000, "CAD")).toBe("$45k–71k");
    expect(salaryLabel(28, 35, "CAD")).toBe("$28–35/hr");
  });

  it("removes bold markup", () => {
    expect(stripMarkup("Built with **Docker** and **AWS**")).toBe("Built with Docker and AWS");
  });
});
