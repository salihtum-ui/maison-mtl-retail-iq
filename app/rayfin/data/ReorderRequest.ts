import { date, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/**
 * A reorder request written by a Maison MTL employee. Requests are immutable: each user can create and read only their
 * own rows. The SQL database replicates to OneLake, where the medallion validates the request for buyer approval.
 */
@entity()
@role('authenticated', ['create', 'read'], {
  policy: (claims, item) => claims.sub.eq(item.user_id),
})
export class ReorderRequest {
  @uuid() id!: string;
  @text({ max: 20 }) storeCode!: string;
  @text({ max: 20 }) sku!: string;
  @text({ max: 120 }) productName!: string;
  @int({ min: 1, max: 1000 }) quantity!: number;
  @text({ max: 20 }) urgency!: string;
  @date() neededBy!: Date;
  @text({ max: 500 }) note!: string;
  @text({ max: 40 }) source!: string;
  @int({ optional: true }) recommendedQty?: number;
  @text({ max: 20, optional: true }) riskLevel?: string;
  @date() submittedAt!: Date;
  @text({ max: 200 }) submittedByName!: string;
  @text({ max: 200 }) user_id!: string;
}
