import {
  RealitySentinel,
  predictionContractHash,
  type PredictionContract,
  type RealitySignal,
} from '../core/reality-sentinel';

function contract(): PredictionContract {
  return {
    id: 'contract-1',
    decision: 'Proceed with controlled launch',
    createdAt: '2026-09-27T20:00:00.000Z',
    assumptions: [
      { id: 'demand', statement: 'Validated demand remains present.', weight: 50, critical: true },
      { id: 'delivery', statement: 'Delivery remains operationally feasible.', weight: 30 },
      { id: 'timing', statement: 'Timing remains favorable.', weight: 20 },
    ],
  };
}

describe('RealitySentinel', (): void => {
  test('ignores unverified signals and stays stable', (): void => {
    const sentinel = new RealitySentinel();
    const result = sentinel.assess(contract(), [
      {
        id: 'rumor-1',
        assumptionId: 'demand',
        direction: 'CONTRADICTS',
        strength: 100,
        verified: false,
      },
    ]);

    expect(result.driftScore).toBe(0);
    expect(result.state).toBe('STABLE');
    expect(result.reanalyze).toBe(false);
    expect(result.ignoredSignalIds).toEqual(['rumor-1']);
  });

  test('uses only the strongest contradiction per assumption', (): void => {
    const sentinel = new RealitySentinel();
    const signals: RealitySignal[] = [
      { id: 'd1', assumptionId: 'delivery', direction: 'CONTRADICTS', strength: 60, verified: true },
      { id: 'd2', assumptionId: 'delivery', direction: 'CONTRADICTS', strength: 80, verified: true },
      { id: 'd3', assumptionId: 'delivery', direction: 'CONTRADICTS', strength: 70, verified: true },
    ];

    const result = sentinel.assess(contract(), signals);

    expect(result.driftScore).toBe(24);
    expect(result.state).toBe('WATCH');
    expect(result.brokenAssumptionIds).toEqual(['delivery']);
    expect(result.reanalyze).toBe(false);
  });

  test('escalates a strongly contradicted critical assumption to CRITICAL', (): void => {
    const sentinel = new RealitySentinel();
    const result = sentinel.assess(contract(), [
      {
        id: 'demand-break',
        assumptionId: 'demand',
        direction: 'CONTRADICTS',
        strength: 85,
        verified: true,
        evidenceId: 'evidence-42',
      },
    ]);

    expect(result.driftScore).toBe(43);
    expect(result.state).toBe('CRITICAL');
    expect(result.reanalyze).toBe(true);
    expect(result.brokenAssumptionIds).toEqual(['demand']);
    expect(result.reasons).toEqual(expect.arrayContaining([
      expect.stringContaining('Critical assumption demand'),
    ]));
  });

  test('enters DRIFT when combined verified contradiction crosses the threshold', (): void => {
    const sentinel = new RealitySentinel();
    const result = sentinel.assess(contract(), [
      { id: 'delivery-break', assumptionId: 'delivery', direction: 'CONTRADICTS', strength: 100, verified: true },
      { id: 'timing-break', assumptionId: 'timing', direction: 'CONTRADICTS', strength: 50, verified: true },
    ]);

    expect(result.driftScore).toBe(40);
    expect(result.state).toBe('DRIFT');
    expect(result.reanalyze).toBe(true);
  });

  test('produces a deterministic contract hash independent of assumption order', (): void => {
    const original = contract();
    const reordered: PredictionContract = {
      ...original,
      assumptions: [...original.assumptions].reverse(),
    };

    expect(predictionContractHash(original)).toBe(predictionContractHash(reordered));
  });

  test('rejects malformed prediction contracts and invalid strengths', (): void => {
    const sentinel = new RealitySentinel();
    const invalid = contract();
    invalid.assumptions[0] = { ...invalid.assumptions[0], weight: 0 };

    expect(() => sentinel.assess(invalid, [])).toThrow('weight');
    expect(() => sentinel.assess(contract(), [
      { id: 'bad', assumptionId: 'demand', direction: 'CONTRADICTS', strength: 101, verified: true },
    ])).toThrow('strength');
  });
});
