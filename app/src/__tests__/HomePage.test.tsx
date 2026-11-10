import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Advisor } from '@/components/Advisor';
import { HomePage } from '@/pages/HomePage';
import { askMtlAdvisor } from '@/services/advisor';
import { createReorderRequest, validateDraft } from '@/services/requests';

import { fixture } from './fixtures';

vi.mock('@/hooks/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1', name: 'Demo Buyer', email: 'demo@contoso.com' }, signOut: vi.fn() }),
}));

vi.mock('@/services/requests', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/requests')>();
  return {
    ...actual,
    getMyReorderRequests: vi.fn().mockResolvedValue([]),
    getMyReorderReviews: vi.fn().mockResolvedValue([]),
    createReorderRequest: vi.fn().mockResolvedValue({ id: 'request-1' }),
  };
});

vi.mock('@/services/advisor', () => ({
  askMtlAdvisor: vi.fn().mockResolvedValue({
    status: 'answered', message: '', attempts: 1,
    answer: 'Montréal Centre-Ville led with **$459,997** in the last 28 days.',
    generatedAt: '2026-11-04T12:00:00Z', agentName: 'MTL Retail IQ Advisor', ontologyName: 'MtlRetailOntology', readOnly: true,
  }),
}));

describe('MTL Retail IQ', () => {
  it('shows governed KPIs and the critical stock alert', () => {
    render(<HomePage initialData={fixture} />);
    expect(screen.getByText('$3.01M')).toBeInTheDocument();
    expect(screen.getByText('+21.3% vs same 28 days LY')).toBeInTheDocument();
    expect(screen.getByText(/Women's Waterproof Winter Boot/)).toBeInTheDocument();
  });

  it('turns an ML recommendation into a reorder request', async () => {
    const user = userEvent.setup();
    render(<HomePage initialData={fixture} />);
    await user.click(screen.getByRole('button', { name: /Forecast & stock risk/ }));
    const table = screen.getByRole('table');
    await user.click(within(table).getByRole('button', { name: 'Request' }));
    expect(screen.getByRole('heading', { name: 'New reorder request' })).toBeInTheDocument();
    expect(screen.getByLabelText('Quantity (units)')).toHaveValue(36);
    await user.click(screen.getByRole('button', { name: 'Submit reorder request' }));
    expect(createReorderRequest).toHaveBeenCalledWith(expect.objectContaining({
      storeCode: 'MT-CV', sku: 'W-FTW-601', quantity: 36, urgency: 'Critical', source: 'ML recommendation', recommendedQty: 36,
    }), 'Demo Buyer');
    expect(await screen.findByText(/Request saved to the app SQL database/)).toBeInTheDocument();
  });

  it('asks the protected advisor function', async () => {
    const user = userEvent.setup();
    render(<Advisor />);
    await user.click(screen.getByRole('button', { name: /highest net sales/i }));
    expect(await screen.findByText(/Montréal Centre-Ville led with/)).toBeInTheDocument();
  });

  it('shows a friendly message instead of agent failure prose', async () => {
    vi.mocked(askMtlAdvisor).mockResolvedValueOnce({
      status: 'unavailable', answer: '', attempts: 2, readOnly: true, generatedAt: '2026-11-06T12:00:00Z',
      message: "MTL IQ couldn't retrieve the data for this question. Try again in a moment, or narrow it to one store, category or period.",
      agentName: 'MTL Retail IQ Advisor', ontologyName: 'MtlRetailOntology',
    });
    const user = userEvent.setup();
    render(<Advisor />);
    await user.click(screen.getByRole('button', { name: /pending reorder requests/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent("couldn't retrieve the data");
    expect(screen.queryByText(/context size|tool interface/i)).not.toBeInTheDocument();
  });

  it('validates reorder drafts', () => {
    const draft = { storeCode: 'MT-CV', sku: 'W-FTW-601', productName: 'Boot', quantity: 0, urgency: 'Urgent',
      neededBy: new Date('2026-11-10'), note: '', source: 'Employee request' };
    expect(validateDraft(draft)).toMatch(/Quantity/);
    expect(validateDraft({ ...draft, quantity: 12 })).toBeNull();
    expect(validateDraft({ ...draft, quantity: 12, urgency: 'Whenever' })).toMatch(/urgency/);
  });
});
