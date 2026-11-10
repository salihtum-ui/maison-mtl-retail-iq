import { decimal, entity, role, text, uuid } from '@microsoft/rayfin-core';

/** Daily actual units (last 56 days) and ML forecast units (next 28 days) by department (read-only). */
@entity()
@role('authenticated', ['read'])
export class DemandPoint {
  @uuid() id!: string;
  @text({ max: 10 }) day!: string;
  @text({ max: 40 }) department!: string;
  @text({ max: 10 }) kind!: string;
  @decimal({ precision: 12, scale: 2 }) units!: number;
  @decimal({ precision: 12, scale: 2, optional: true }) unitsLow?: number;
  @decimal({ precision: 12, scale: 2, optional: true }) unitsHigh?: number;
}
