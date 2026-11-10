import { entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** Medallion validation outcome for a reorder request, written back by app_sync.py; owners read only their own. */
@entity()
@role('authenticated', ['read'], {
  policy: (claims, item) => claims.sub.eq(item.user_id),
})
export class ReorderReview {
  @uuid() id!: string;
  @text({ unique: true, max: 64 }) requestId!: string;
  @text({ max: 200 }) user_id!: string;
  @text({ max: 40 }) status!: string;
  @text({ max: 300 }) message!: string;
  @text({ max: 20, optional: true }) riskLevel?: string;
  @int({ optional: true }) recommendedQty?: number;
  @text({ max: 30 }) reviewedAt!: string;
}
