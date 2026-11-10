import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppErrorBoundary } from '@/components/AppErrorBoundary';

describe('render failure recovery', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it('shows and logs render errors instead of leaving a blank page', () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    function BrokenView(): never { throw new Error('Unexpected date value'); }
    render(<AppErrorBoundary><BrokenView /></AppErrorBoundary>);
    expect(screen.getByRole('alert')).toHaveTextContent('Unexpected date value');
    expect(screen.getByRole('button', { name: 'Reload application' })).toBeInTheDocument();
    expect(log).toHaveBeenCalledWith('MTL Retail IQ rendering failed', expect.any(Error), expect.any(String));
  });
});
