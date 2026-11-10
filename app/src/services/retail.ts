import type { CategoryKpi } from '../../rayfin/data/CategoryKpi';
import type { DemandPoint } from '../../rayfin/data/DemandPoint';
import type { KpiSnapshot } from '../../rayfin/data/KpiSnapshot';
import type { MonthlyTrend } from '../../rayfin/data/MonthlyTrend';
import type { ProductKpi } from '../../rayfin/data/ProductKpi';
import type { StockRisk } from '../../rayfin/data/StockRisk';
import type { StoreKpi } from '../../rayfin/data/StoreKpi';
import { getRayfinClient } from './rayfinClient';

export type RetailData = {
  snapshot: KpiSnapshot | null;
  stores: StoreKpi[];
  categories: CategoryKpi[];
  products: ProductKpi[];
  trends: MonthlyTrend[];
  demand: DemandPoint[];
  risks: StockRisk[];
};

const num = (value: unknown): number => (value === null || value === undefined ? 0 : Number(value));
const opt = (value: unknown): number | undefined => (value === null || value === undefined ? undefined : Number(value));

export async function loadRetailData(): Promise<RetailData> {
  const data = getRayfinClient().data;
  const [snapshots, stores, categories, products, trends, demand, risks] = await Promise.all([
    data.KpiSnapshot.select(['snapshotDate', 'publishedAt', 'netSalesLast28', 'netSalesLast28LY', 'last28GrowthPct',
      'unitsLast28', 'grossMarginPctLast28', 'netSalesYTD', 'ytdGrowthPct', 'storeOnHandUnits', 'storeOnOrderUnits',
      'dcOnHandUnits', 'inventoryCost', 'positions', 'outOfStockPositions', 'belowReorderPointPositions',
      'criticalPositions', 'highRiskPositions', 'recommendedUnitsHighRisk', 'forecastUnits28', 'forecastNetSales28',
      'forecastWapePct', 'baselineWapePct', 'forecastModel', 'stockModel', 'generatedAt']).first(5).execute(),
    data.StoreKpi.select(['storeCode', 'storeName', 'city', 'region', 'netSalesLast28', 'netSalesLast28LY', 'last28GrowthPct',
      'unitsLast28', 'grossMarginPctLast28', 'netSalesYTD', 'ytdGrowthPct', 'onHandUnits', 'outOfStockPositions',
      'belowReorderPointPositions', 'highRiskPositions', 'forecastUnits28']).orderBy({ netSalesLast28: 'desc' }).first(50).execute(),
    data.CategoryKpi.select(['categoryId', 'department', 'category', 'netSalesLast28', 'last28GrowthPct', 'unitsLast28',
      'grossMarginPctLast28', 'onHandUnits', 'sellThroughPct', 'weeksOfSupply', 'outOfStockPositions'])
      .orderBy({ netSalesLast28: 'desc' }).first(100).execute(),
    data.ProductKpi.select(['sku', 'productName', 'department', 'category', 'brand', 'supplierCode', 'unitPrice', 'casePack',
      'netSalesLast28', 'unitsLast28', 'last28GrowthPct', 'onHandUnits', 'dcOnHandUnits', 'outOfStockStores',
      'belowReorderPointStores', 'forecastUnits28']).orderBy({ netSalesLast28: 'desc' }).first(200).execute(),
    data.MonthlyTrend.select(['month', 'department', 'netSales', 'netSalesLY', 'units']).orderBy({ month: 'asc' }).first(500).execute(),
    data.DemandPoint.select(['day', 'department', 'kind', 'units', 'unitsLow', 'unitsHigh']).orderBy({ day: 'asc' }).first(1000).execute(),
    data.StockRisk.select(['positionId', 'storeCode', 'storeName', 'sku', 'productName', 'department', 'category', 'onHandUnits',
      'onOrderUnits', 'reorderPointUnits', 'daysOfSupply', 'stockStatus', 'forecast28Units', 'predictedLowStockDate',
      'predictedDaysToLow', 'riskLevel', 'riskRank', 'recommendedReorderQty', 'recommendedAction', 'dcOnHandUnits'])
      .orderBy({ positionId: 'asc' }).first(2000).execute(),
  ]);
  const snapshot = snapshots[0] ?? null;
  return {
    snapshot: snapshot && {
      ...snapshot,
      netSalesLast28: num(snapshot.netSalesLast28), netSalesLast28LY: num(snapshot.netSalesLast28LY),
      last28GrowthPct: num(snapshot.last28GrowthPct), grossMarginPctLast28: num(snapshot.grossMarginPctLast28),
      netSalesYTD: num(snapshot.netSalesYTD), ytdGrowthPct: num(snapshot.ytdGrowthPct), inventoryCost: num(snapshot.inventoryCost),
      forecastNetSales28: num(snapshot.forecastNetSales28), forecastWapePct: num(snapshot.forecastWapePct),
      baselineWapePct: num(snapshot.baselineWapePct),
    } as KpiSnapshot,
    stores: stores.map(s => ({ ...s, netSalesLast28: num(s.netSalesLast28), netSalesLast28LY: num(s.netSalesLast28LY),
      last28GrowthPct: num(s.last28GrowthPct), grossMarginPctLast28: num(s.grossMarginPctLast28), netSalesYTD: num(s.netSalesYTD),
      ytdGrowthPct: num(s.ytdGrowthPct) }) as StoreKpi),
    categories: categories.map(c => ({ ...c, netSalesLast28: num(c.netSalesLast28), last28GrowthPct: opt(c.last28GrowthPct),
      grossMarginPctLast28: opt(c.grossMarginPctLast28), sellThroughPct: opt(c.sellThroughPct), weeksOfSupply: opt(c.weeksOfSupply) }) as CategoryKpi),
    products: products.map(p => ({ ...p, unitPrice: num(p.unitPrice), netSalesLast28: num(p.netSalesLast28),
      last28GrowthPct: opt(p.last28GrowthPct) }) as ProductKpi),
    trends: trends.map(t => ({ ...t, netSales: num(t.netSales), netSalesLY: opt(t.netSalesLY) }) as MonthlyTrend),
    demand: demand.map(d => ({ ...d, units: num(d.units), unitsLow: opt(d.unitsLow), unitsHigh: opt(d.unitsHigh) }) as DemandPoint),
    risks: risks.map(r => ({ ...r, daysOfSupply: opt(r.daysOfSupply), forecast28Units: num(r.forecast28Units) }) as StockRisk),
  };
}
