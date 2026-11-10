import { decimal, entity, int, role, text, uuid } from '@microsoft/rayfin-core';

/** Monthly net sales by department, with the same month last year (read-only in the app). */
@entity()
@role('authenticated', ['read'])
export class MonthlyTrend {
  @uuid() id!: string;
  @text({ max: 7 }) month!: string;
  @text({ max: 40 }) department!: string;
  @decimal({ precision: 14, scale: 2 }) netSales!: number;
  @decimal({ precision: 14, scale: 2, optional: true }) netSalesLY?: number;
  @int() units!: number;
}
