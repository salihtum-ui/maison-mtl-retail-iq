import { CategoryKpi } from './CategoryKpi.js';
import { DemandPoint } from './DemandPoint.js';
import { KpiSnapshot } from './KpiSnapshot.js';
import { MonthlyTrend } from './MonthlyTrend.js';
import { ProductKpi } from './ProductKpi.js';
import { ReorderRequest } from './ReorderRequest.js';
import { ReorderReview } from './ReorderReview.js';
import { StockRisk } from './StockRisk.js';
import { StoreKpi } from './StoreKpi.js';

export type MtlAppSchema = {
  KpiSnapshot: KpiSnapshot;
  StoreKpi: StoreKpi;
  CategoryKpi: CategoryKpi;
  ProductKpi: ProductKpi;
  MonthlyTrend: MonthlyTrend;
  DemandPoint: DemandPoint;
  StockRisk: StockRisk;
  ReorderRequest: ReorderRequest;
  ReorderReview: ReorderReview;
};

export const schema = [KpiSnapshot, StoreKpi, CategoryKpi, ProductKpi, MonthlyTrend, DemandPoint, StockRisk,
  ReorderRequest, ReorderReview];
