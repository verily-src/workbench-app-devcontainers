import { describe, expect, it } from "vitest";
import { computeEnrichment, computeOddsRatio, fisherTwoSided } from "./statistics";

describe("computeEnrichment", () => {
  it("calls a departure enriched only when the whole interval sits above 1", () => {
    const result = computeEnrichment(6, 200, 28, 24000)!;
    expect(result.ratio).toBeCloseTo(25.7, 1);
    expect(result.verdict).toBe("enriched");
    expect(result.pValue).toBeLessThan(0.001);
    expect(result.oddsRatio).toBeCloseTo(33.4, 1);
    expect(result.ci![0]).toBeGreaterThan(1);
    expect(result.strength).toBeCloseTo(Math.log(result.ci![0]), 6);
    expect(result.matchedAc).toBe(6);
    expect(result.expectedMatchedAc).toBeCloseTo(0.233, 2);
    expect(result.lean).toBeNull();
  });

  it("calls a departure depleted only when the whole interval sits below 1", () => {
    const result = computeEnrichment(1, 2000, 300, 20000)!;
    expect(result.verdict).toBe("depleted");
    expect(result.ci![1]).toBeLessThan(1);
    expect(result.strength).toBeGreaterThan(0);
  });

  it("calls frequencies similar when the interval rules out a 2-fold difference either way", () => {
    const result = computeEnrichment(30, 1000, 600, 20000)!;
    expect(result.verdict).toBe("similar");
    expect(result.ci![0]).toBeGreaterThanOrEqual(0.5);
    expect(result.ci![1]).toBeLessThanOrEqual(2);
    expect(result.strength).toBe(0);
  });

  it("calls a wide interval that straddles 1 inconclusive, however far the point estimate sits from 1", () => {
    // The reviewer's PCSK9 case in spirit: a 0.4× point estimate on three alleles, interval taking in 1.
    const result = computeEnrichment(3, 600, 5577, 479860)!;
    expect(result.ratio).toBeCloseTo(0.43, 2);
    expect(result.ci![0]).toBeLessThan(1);
    expect(result.ci![1]).toBeGreaterThan(1);
    expect(result.verdict).toBe("inconclusive");
    expect(result.lean).toBe("fewer");

    // One allele at twice the cohort rate: a wide interval, no verdict.
    const fluke = computeEnrichment(1, 100, 100, 20000)!;
    expect(fluke.ratio).toBeCloseTo(2, 0);
    expect(fluke.verdict).toBe("inconclusive");
    expect(fluke.lean).toBe("more");
  });

  it("won't call enrichment on fewer than three matched alleles, even when the interval clears 1", () => {
    // One matched allele against two in the rest of a 480k-allele cohort: the interval sits well
    // above 1 and the exact test is small, but one carrier is not a finding.
    const single = computeEnrichment(1, 262, 3, 481436)!;
    expect(single.ci![0]).toBeGreaterThan(1);
    expect(single.pValue).toBeLessThan(0.01);
    expect(single.verdict).toBe("inconclusive");
    expect(single.lean).toBe("more");
    expect(single.strength).toBe(0);

    const three = computeEnrichment(3, 262, 5, 481436)!;
    expect(three.verdict).toBe("enriched");
  });

  it("doesn't call a variant enriched when Fisher's exact test isn't significant", () => {
    // Three of four matched alleles against none of the other four: p = 0.143. The old bound
    // treated the matched odds as known and put the interval's lower end at 2.69, calling it enriched.
    const result = computeEnrichment(3, 4, 3, 8)!;
    expect(result.pValue).toBeCloseTo(0.143, 3);
    expect(result.ci![0]).toBeLessThan(1);
    expect(result.verdict).toBe("inconclusive");
    expect(result.lean).toBe("more");
  });

  it("bounds a zero count by the exact interval's open side instead of inventing an interval", () => {
    // 0 of 262 against 3 of 481,436, where 0.002 were expected: no information either way.
    const result = computeEnrichment(0, 262, 3, 481436)!;
    expect(result.verdict).toBe("inconclusive");
    expect(result.ratio).toBe(0);
    expect(result.oddsRatio).toBe(0);
    expect(result.ci![0]).toBe(0);
    expect(result.ci![1]).toBeGreaterThan(1);
    expect(result.expectedMatchedAc).toBeCloseTo(0.0016, 3);
    expect(result.lean).toBe("fewer");

    // 0 of 400 where 100 were expected: a real shortfall, and the bound says so.
    const shortfall = computeEnrichment(0, 400, 6000, 24000)!;
    expect(shortfall.expectedMatchedAc).toBe(100);
    expect(shortfall.ci![1]).toBeLessThan(1);
    expect(shortfall.verdict).toBe("depleted");

    // Carriers among the matched and none anywhere else: enriched, with an open upper end.
    const only = computeEnrichment(3, 200, 3, 24000)!;
    expect(only.oddsRatio).toBe(Infinity);
    expect(only.ci![0]).toBeGreaterThan(1);
    expect(only.ci![1]).toBe(Infinity);
    expect(only.verdict).toBe("enriched");
  });

  it("calls a one-participant cohort with no carriers inconclusive, with a finite bound and a usable strength", () => {
    // One participant contributes two alleles. The rule of three once made this bound negative, which
    // read as an interval below 1: a "depleted" call with a NaN strength that broke the rail's sort.
    const one = computeEnrichment(0, 2, 5577, 479860)!;
    expect(one.ci![0]).toBe(0);
    expect(one.ci![1]).toBeGreaterThan(1);
    expect(Number.isFinite(one.ci![1])).toBe(true);
    expect(one.verdict).toBe("inconclusive");
    expect(one.strength).toBe(0);
    expect(one.lean).toBe("fewer");
  });

  it("has nothing to say when nobody carries the allele, and nothing to divide by without alleles", () => {
    const nobody = computeEnrichment(0, 200, 0, 24000)!;
    expect(nobody.ratio).toBe(1);
    expect(nobody.ci).toBeNull();
    expect(nobody.verdict).toBe("inconclusive");
    expect(nobody.lean).toBeNull();
    expect(computeEnrichment(3, 0, 28, 24000)).toBeNull();
  });

  it("makes no comparison when the matched counts can't be nested in the cohort's", () => {
    // More matched carriers than the whole cohort has: the sources disagree, and comparing the
    // matched group with a cohort that contains it would be neither separate groups nor a real one.
    expect(computeEnrichment(5, 200, 3, 24000)).toBeNull();
    // More matched alleles than the cohort has.
    expect(computeEnrichment(1, 30000, 28, 24000)).toBeNull();
    // Nested counts, even with every cohort-wide carrier among the matched, still compare.
    expect(computeEnrichment(3, 200, 3, 24000)!.verdict).toBe("enriched");
  });

  it("carries the ancestry-adjusted expectation through when given", () => {
    expect(computeEnrichment(6, 200, 28, 24000, { expectedAdjustedAc: 1.0 })!.expectedAdjustedAc).toBe(1.0);
    expect(computeEnrichment(6, 200, 28, 24000)!.expectedAdjustedAc).toBeNull();
  });
});

describe("computeOddsRatio", () => {
  it("matches R's fisher.test interval", () => {
    // Lady tasting tea, [[3,1],[1,3]]: fisher.test gives 0.2117329 to 621.9337. Its upper end is
    // loose (uniroot's default tolerance on 1/ψ); solving ψ⁴ / (1 + 16ψ + 36ψ² + 16ψ³ + ψ⁴) = 0.975
    // directly gives 626.2435.
    const tea = computeOddsRatio(3, 1, 1, 3);
    expect(tea.oddsRatio).toBe(9);
    expect(tea.ci![0]).toBeCloseTo(0.2117329, 5);
    expect(tea.ci![1]).toBeCloseTo(626.2435, 2);
  });

  it("is wider than Woolf's interval at small counts", () => {
    // Woolf gives 0.96 to 4.67 here; the exact interval reaches further on both sides.
    const { oddsRatio, ci } = computeOddsRatio(10, 90, 20, 380);
    expect(oddsRatio).toBeCloseTo(2.11, 2);
    expect(ci![0]).toBeLessThan(0.96);
    expect(ci![1]).toBeGreaterThan(4.67);
    expect(ci![0]).toBeLessThan(oddsRatio);
    expect(ci![1]).toBeGreaterThan(oddsRatio);
  });

  it("leaves a side open when the count is at the edge the margins allow", () => {
    const none = computeOddsRatio(0, 100, 5, 495);
    expect(none.oddsRatio).toBe(0);
    expect(none.ci![0]).toBe(0);
    expect(none.ci![1]).toBeGreaterThan(1);
    expect(Number.isFinite(none.ci![1])).toBe(true);

    const all = computeOddsRatio(3, 97, 0, 500);
    expect(all.oddsRatio).toBe(Infinity);
    expect(all.ci![1]).toBe(Infinity);
    expect(all.ci![0]).toBeGreaterThan(1);

    // One participant's two alleles, neither a carrier: still a finite, positive bound.
    const one = computeOddsRatio(0, 2, 28, 23970);
    expect(one.ci![0]).toBe(0);
    expect(one.ci![1]).toBeGreaterThan(1);
    expect(Number.isFinite(one.ci![1])).toBe(true);
  });

  it("doesn't treat the non-empty side's odds as known", () => {
    // Three of four matched alleles carry it and none of the rest's four: Fisher's p is 0.143, so
    // the interval must take in 1. The old zero-event bound put its lower end at 2.69.
    const { ci } = computeOddsRatio(3, 1, 0, 4);
    expect(fisherTwoSided(3, 1, 0, 4)).toBeCloseTo(0.143, 3);
    expect(ci![0]).toBeLessThan(1);
    expect(ci![1]).toBe(Infinity);
  });

  it("excludes 1 only when the matching one-sided exact test is significant", () => {
    // The interval's ends are the 2.5% one-sided tails, so excluding 1 means the observed tail at
    // ψ = 1 is under 2.5%, which also puts the two-sided Fisher p under 5%.
    for (let a = 0; a <= 8; a++)
      for (let b = 0; b <= 12; b++)
        for (let c = 0; c <= 8; c++)
          for (let d = 0; d <= 12; d++) {
            const { ci } = computeOddsRatio(a, b, c, d);
            if (ci && (ci[0] > 1 || ci[1] < 1)) expect(fisherTwoSided(a, b, c, d), `[[${a},${b}],[${c},${d}]]`).toBeLessThan(0.05);
          }
  });

  it("stays fast for a common variant in a large matched cohort", () => {
    // 50,000 matched participants and a variant carried by 30% of them: a support of 100,000
    // values. Summing every value on each of the bisection's steps took half a second here;
    // summing from the mode outward takes milliseconds. The budget is loose for slow CI machines.
    const started = performance.now();
    const { oddsRatio, ci } = computeOddsRatio(30000, 70000, 120000, 359860);
    expect(performance.now() - started).toBeLessThan(50);
    expect(oddsRatio).toBeCloseTo(1.285, 3);
    expect(ci![0]).toBeGreaterThan(1);
    expect(ci![0]).toBeLessThan(oddsRatio);
    expect(ci![1]).toBeGreaterThan(oddsRatio);
    // Bounds this tight on a table this large: Woolf's interval is 1.264 to 1.306 here, and the
    // exact one agrees to three figures.
    expect(ci![0]).toBeCloseTo(1.264, 2);
    expect(ci![1]).toBeCloseTo(1.306, 2);
  });

  it("handles cohort-sized counts", () => {
    const { oddsRatio, ci } = computeOddsRatio(12, 770, 5565, 474295);
    expect(ci![0]).toBeGreaterThan(0);
    expect(ci![0]).toBeLessThan(oddsRatio);
    expect(ci![1]).toBeGreaterThan(oddsRatio);
  });

  it("leaves the interval undefined when the margins allow only the observed table", () => {
    expect(computeOddsRatio(0, 100, 0, 500)).toEqual({ oddsRatio: 1, ci: null });
    expect(computeOddsRatio(4, 0, 6, 0)).toEqual({ oddsRatio: 1, ci: null });
  });
});

describe("fisherTwoSided", () => {
  it("matches a textbook value", () => {
    // Lady tasting tea, [[3,1],[1,3]]: two-sided p = 0.4857.
    expect(fisherTwoSided(3, 1, 1, 3)).toBeCloseTo(0.4857, 3);
  });

  it("returns 1 for a table with no information", () => {
    expect(fisherTwoSided(0, 10, 0, 10)).toBe(1);
    expect(fisherTwoSided(5, 0, 5, 0)).toBe(1);
  });
});
