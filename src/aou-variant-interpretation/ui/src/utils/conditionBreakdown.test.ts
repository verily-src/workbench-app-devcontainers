import { describe, expect, it } from "vitest";
import colors, { CONDITION_SERIES } from "../libs/colors";
import { conditionBreakdown } from "./conditionBreakdown";

const HCM = { conceptId: 9000040, name: "Hypertrophic cardiomyopathy", estimatedParticipantCount: 212, participantCount: 214 };
const LQT = { conceptId: 9000060, name: "Long QT syndrome", estimatedParticipantCount: 128, participantCount: 131 };
const TOF = { conceptId: 9000010, name: "Tetralogy of Fallot", estimatedParticipantCount: 47, participantCount: 49 };

describe("conditionBreakdown", () => {
  it("gives each condition its 'only' participants in its own hue, then everyone with more than one in the neutral", () => {
    const segments = conditionBreakdown(
      [HCM, LQT, TOF],
      [
        { conceptIds: [9000040], count: 201 },
        { conceptIds: [9000060], count: 119 },
        { conceptIds: [9000010], count: 47 },
        { conceptIds: [9000040, 9000060], count: 11 },
        { conceptIds: [9000040, 9000010], count: 1 },
        { conceptIds: [9000040, 9000060, 9000010], count: 1 },
      ],
      380,
    );

    expect(segments.map((s) => [s.label, s.count, s.color])).toEqual([
      ["Hypertrophic cardiomyopathy only", 201, CONDITION_SERIES[0]],
      ["Long QT syndrome only", 119, CONDITION_SERIES[1]],
      ["Tetralogy of Fallot only", 47, CONDITION_SERIES[2]],
      ["More than one", 13, colors.conditionOverlap],
    ]);
    expect(segments.reduce((sum, s) => sum + s.count, 0)).toBe(380);
    expect(segments[0].percent).toBeCloseTo(52.9, 1);
  });

  it("leaves out a condition nobody has on its own, and the overlap when there is none", () => {
    // Everyone with Tetralogy also has HCM: no "Tetralogy only" segment.
    expect(
      conditionBreakdown([HCM, TOF], [{ conceptIds: [9000040], count: 212 }, { conceptIds: [9000040, 9000010], count: 2 }], 214).map(
        (s) => s.label,
      ),
    ).toEqual(["Hypertrophic cardiomyopathy only", "More than one"]);
    expect(
      conditionBreakdown([HCM, LQT], [{ conceptIds: [9000040], count: 214 }, { conceptIds: [9000060], count: 131 }], 345).map((s) => s.label),
    ).toEqual(["Hypertrophic cardiomyopathy only", "Long QT syndrome only"]);
    expect(conditionBreakdown([HCM], [], 0)).toEqual([]);
  });
});
