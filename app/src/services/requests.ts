import type { ReorderRequest } from '../../rayfin/data/ReorderRequest';
import type { ReorderReview } from '../../rayfin/data/ReorderReview';
import { getRayfinClient } from './rayfinClient';

export type ReorderDraft = Pick<ReorderRequest,
  'storeCode' | 'sku' | 'productName' | 'quantity' | 'urgency' | 'neededBy' | 'note' | 'source' | 'recommendedQty' | 'riskLevel'>;

export const URGENCIES = ['Standard', 'Urgent', 'Critical'] as const;

export function validateDraft(draft: ReorderDraft): string | null {
  if (!draft.storeCode) return 'Choose a store.';
  if (!draft.sku) return 'Choose a product.';
  if (!Number.isInteger(draft.quantity) || draft.quantity < 1 || draft.quantity > 1000) return 'Quantity must be a whole number from 1 to 1,000.';
  if (!URGENCIES.includes(draft.urgency as (typeof URGENCIES)[number])) return 'Choose an urgency.';
  if (!(draft.neededBy instanceof Date) || Number.isNaN(draft.neededBy.getTime())) return 'Choose a needed-by date.';
  if (draft.note.length > 500) return 'Keep the note under 500 characters.';
  return null;
}

export async function createReorderRequest(draft: ReorderDraft, submitterName: string) {
  const problem = validateDraft(draft);
  if (problem) throw new Error(problem);
  const client = getRayfinClient();
  const session = client.auth.getSession();
  if (!session.isAuthenticated || !session.user) throw new Error('Sign in again before submitting a request.');
  return client.data.ReorderRequest.create({
    ...draft,
    note: draft.note.trim(),
    submittedAt: new Date(),
    submittedByName: submitterName.slice(0, 200),
    user_id: session.user.id,
  });
}

export async function getMyReorderRequests(): Promise<ReorderRequest[]> {
  return getRayfinClient().data.ReorderRequest
    .select(['id', 'storeCode', 'sku', 'productName', 'quantity', 'urgency', 'neededBy', 'note', 'source', 'recommendedQty',
      'riskLevel', 'submittedAt', 'submittedByName', 'user_id'])
    .orderBy({ submittedAt: 'desc' })
    .first(500)
    .execute();
}

export async function getMyReorderReviews(): Promise<ReorderReview[]> {
  return getRayfinClient().data.ReorderReview
    .select(['id', 'requestId', 'user_id', 'status', 'message', 'riskLevel', 'recommendedQty', 'reviewedAt'])
    .first(500)
    .execute();
}
