import { decimal, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** Product (SKU) chain roll-up with sales, stock and forecast (read-only in the app). */
@entity()
@role('authenticated', ['read'])
export class ProductKpi {
  @uuid() id!: string;
  @text({ unique: true, max: 20 }) sku!: string;
  @text({ max: 120 }) productName!: string;
  @text({ max: 40 }) department!: string;
  @text({ max: 60 }) category!: string;
  @text({ max: 60 }) brand!: string;
  @text({ max: 20 }) supplierCode!: string;
  @decimal({ precision: 10, scale: 2 }) unitPrice!: number;
  @int() casePack!: number;
  @decimal({ precision: 14, scale: 2 }) netSalesLast28!: number;
  @int() unitsLast28!: number;
  @decimal({ precision: 8, scale: 2, optional: true }) last28GrowthPct?: number;
  @int() onHandUnits!: number;
  @int() dcOnHandUnits!: number;
  @int() outOfStockStores!: number;
  @int() belowReorderPointStores!: number;
  @int() forecastUnits28!: number;
}
