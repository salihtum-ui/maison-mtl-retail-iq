import { decimal, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** ML low-stock prediction and reorder recommendation per store x SKU (read-only in the app). */
@entity()
@role('authenticated', ['read'])
export class StockRisk {
  @uuid() id!: string;
  @text({ unique: true, max: 50 }) positionId!: string;
  @text({ max: 20 }) storeCode!: string;
  @text({ max: 100 }) storeName!: string;
  @text({ max: 20 }) sku!: string;
  @text({ max: 120 }) productName!: string;
  @text({ max: 40 }) department!: string;
  @text({ max: 60 }) category!: string;
  @int() onHandUnits!: number;
  @int() onOrderUnits!: number;
  @int() reorderPointUnits!: number;
  @decimal({ precision: 10, scale: 1, optional: true }) daysOfSupply?: number;
  @text({ max: 30 }) stockStatus!: string;
  @decimal({ precision: 10, scale: 2 }) forecast28Units!: number;
  @text({ max: 10, optional: true }) predictedLowStockDate?: string;
  @int({ optional: true }) predictedDaysToLow?: number;
  @text({ max: 10 }) riskLevel!: string;
  @int() riskRank!: number;
  @int() recommendedReorderQty!: number;
  @text({ max: 80 }) recommendedAction!: string;
  @int() dcOnHandUnits!: number;
}
