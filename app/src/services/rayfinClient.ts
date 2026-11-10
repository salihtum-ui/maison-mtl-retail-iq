import {
  RayfinClient,
  resolveRayfinConfig,
  type RayfinRuntimeConfig,
} from '@microsoft/rayfin-client';

import type { MtlAppSchema } from '../../rayfin/data/schema';
import type { AppFunctionsSchema } from '../../rayfin/functions/src/types.js';

export interface RayfinClientConfig {
  baseUrl: string;
  publishableKey: string;
  localDev: boolean;
  functionsBaseUrl?: string;
  runtimeConfig?: RayfinRuntimeConfig;
}

let client: RayfinClient<MtlAppSchema, AppFunctionsSchema> | null = null;
let localDev = false;

export async function initRayfinClient(
  config: RayfinClientConfig
): Promise<RayfinClient<MtlAppSchema, AppFunctionsSchema>> {
  if (client) throw new Error('Rayfin client is already initialized.');
  const resolved = await resolveRayfinConfig({
    apiUrl: config.baseUrl,
    publishableKey: config.publishableKey,
    ...config.runtimeConfig,
  });
  client = new RayfinClient<MtlAppSchema, AppFunctionsSchema>({
    baseUrl: resolved.baseUrl!,
    publishableKey: resolved.publishableKey!,
    authStorage: true,
    functionsBaseUrl: config.functionsBaseUrl,
    runtimeConfig: resolved.runtimeConfig,
  });
  localDev = config.localDev;
  return client;
}

export function getRayfinClient(): RayfinClient<MtlAppSchema, AppFunctionsSchema> {
  if (!client) throw new Error('Rayfin client not initialized. Call bootstrapAuth() first.');
  return client;
}

export function isLocalBackend(): boolean {
  return localDev;
}
