import { createRoot } from 'react-dom/client';

import App from '@/App';
import { AppErrorBoundary } from '@/components/AppErrorBoundary';
import { AuthProvider } from '@/hooks/AuthContext';
import { bootstrapAuth } from '@/services/bootstrap';

import './main.css';

const root = createRoot(document.getElementById('root')!);
try {
  const authService = await bootstrapAuth();
  root.render(<AppErrorBoundary><AuthProvider authService={authService}><App /></AuthProvider></AppErrorBoundary>);
} catch (error) {
  console.error('MTL Retail IQ startup failed', error);
  root.render(<main className="startup-error"><h1>MTL Retail IQ</h1>
    <p role="alert">The application could not connect to Fabric. {error instanceof Error ? error.message : 'Please contact the workspace administrator.'}</p>
    <button onClick={() => window.location.reload()}>Try again</button></main>);
}
