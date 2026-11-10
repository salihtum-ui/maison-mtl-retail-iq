import { decimal, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** Department x category KPIs at the snapshot (read-only in the app). */
@entity()
@role('authenticated', ['read'])
export class CategoryKpi {
  @uuid() id!: string;
  @text({ unique: true, max: 100 }) categoryId!: string;
  @text({ max: 40 }) department!: string;
  @text({ max: 60 }) category!: string;
  @decimal({ precision: 14, scale: 2 }) netSalesLast28!: number;
  @decimal({ precision: 8, scale: 2, optional: true }) last28GrowthPct?: number;
  @int() unitsLast28!: number;
  @decimal({ precision: 8, scale: 2, optional: true }) grossMarginPctLast28?: number;
  @int() onHandUnits!: number;
  @decimal({ precision: 8, scale: 2, optional: true }) sellThroughPct?: number;
  @decimal({ precision: 10, scale: 1, optional: true }) weeksOfSupply?: number;
  @int() outOfStockPositions!: number;
}
