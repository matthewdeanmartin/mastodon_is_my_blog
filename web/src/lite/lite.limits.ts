export const LITE_LIMITS = {
  maxCallsPerOperation: 10,
  maxConcurrentCalls: 2,
  pageSize: 40,
  maxPagesPerCollection: 2,
  maxCachedStatusesPerAccount: 80,
  maxCachedOwnStatuses: 160,
  maxCachedFollowing: 500,
  followingPages: 2,
  notificationPages: 2,
  relationshipChunk: 80,
  cacheTtlMs: 5 * 60 * 1000,
} as const;

export class LiteRequestBudget {
  private used = 0;

  get callsUsed(): number {
    return this.used;
  }

  get remaining(): number {
    return LITE_LIMITS.maxCallsPerOperation - this.used;
  }

  spend(): void {
    if (this.used >= LITE_LIMITS.maxCallsPerOperation) {
      throw new Error(`Lite request limit reached (${LITE_LIMITS.maxCallsPerOperation} calls).`);
    }
    this.used += 1;
  }
}
