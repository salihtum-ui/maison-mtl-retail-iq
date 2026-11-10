import { date, decimal, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** Chain KPI snapshot published from the Gold layer by app_sync.py (read-only in the app). */
@entity()
@role('authenticated', ['read'])
export class KpiSnapshot {
  @uuid() id!: string;
  @text({ max: 10 }) snapshotDate!: string;
  @text({ max: 30 }) publishedAt!: string;
  @decimal({ precision: 14, scale: 2 }) netSalesLast28!: number;
  @decimal({ precision: 14, scale: 2 }) netSalesLast28LY!: number;
  @decimal({ precision: 8, scale: 2 }) last28GrowthPct!: number;
  @int() unitsLast28!: number;
  @decimal({ precision: 8, scale: 2 }) grossMarginPctLast28!: number;
  @decimal({ precision: 14, scale: 2 }) netSalesYTD!: number;
  @decimal({ precision: 8, scale: 2 }) ytdGrowthPct!: number;
  @int() storeOnHandUnits!: number;
  @int() storeOnOrderUnits!: number;
  @int() dcOnHandUnits!: number;
  @decimal({ precision: 14, scale: 2 }) inventoryCost!: number;
  @int() positions!: number;
  @int() outOfStockPositions!: number;
  @int() belowReorderPointPositions!: number;
  @int() criticalPositions!: number;
  @int() highRiskPositions!: number;
  @int() recommendedUnitsHighRisk!: number;
  @int() forecastUnits28!: number;
  @decimal({ precision: 14, scale: 2 }) forecastNetSales28!: number;
  @decimal({ precision: 8, scale: 2 }) forecastWapePct!: number;
  @decimal({ precision: 8, scale: 2 }) baselineWapePct!: number;
  @text({ max: 80 }) forecastModel!: string;
  @text({ max: 80 }) stockModel!: string;
  @date() generatedAt!: Date;
}
