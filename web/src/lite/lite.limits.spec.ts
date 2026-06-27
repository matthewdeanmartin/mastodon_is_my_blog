import { describe, expect, it } from 'vitest';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';

describe('LiteRequestBudget', () => {
  it('allows exactly the configured number of calls', () => {
    const budget = new LiteRequestBudget();

    for (let index = 0; index < LITE_LIMITS.maxCallsPerOperation; index += 1) {
      budget.spend();
    }

    expect(budget.callsUsed).toBe(10);
    expect(() => budget.spend()).toThrow('Lite request limit reached');
  });
});
