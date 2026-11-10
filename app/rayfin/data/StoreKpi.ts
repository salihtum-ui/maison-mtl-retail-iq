import { decimal, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** Per-store KPIs at the snapshot (read-only in the app). */
@entity()
@role('authenticated', ['read'])
export class StoreKpi {
  @uuid() id!: string;
  @text({ unique: true, max: 20 }) storeCode!: string;
  @text({ max: 100 }) storeName!: string;
  @text({ max: 60 }) city!: string;
  @text({ max: 60 }) region!: string;
  @decimal({ precision: 14, scale: 2 }) netSalesLast28!: number;
  @decimal({ precision: 14, scale: 2 }) netSalesLast28LY!: number;
  @decimal({ precision: 8, scale: 2 }) last28GrowthPct!: number;
  @int() unitsLast28!: number;
  @decimal({ precision: 8, scale: 2 }) grossMarginPctLast28!: number;
  @decimal({ precision: 14, scale: 2 }) netSalesYTD!: number;
  @decimal({ precision: 8, scale: 2 }) ytdGrowthPct!: number;
  @int() onHandUnits!: number;
  @int() outOfStockPositions!: number;
  @int() belowReorderPointPositions!: number;
  @int() highRiskPositions!: number;
  @int() forecastUnits28!: number;
}
