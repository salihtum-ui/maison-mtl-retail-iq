import { useState } from 'react';

import { useAuth } from '@/hooks/AuthContext';

const msLogo = (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="16"
    height="16"
    viewBox="0 0 21 21"
    className="mr-2"
  >
    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
  </svg>
);

export function AuthPage() {
  const { signIn, fabricAuthEnabled, error: authError } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSignIn = async () => {
    setError(null);
    setIsLoading(true);

    try {
      await signIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to sign in.');
    } finally {
      setIsLoading(false);
    }
  };

  const buttonLabel = isLoading
    ? fabricAuthEnabled
      ? 'Opening Fabric...'
      : 'Signing in...'
    : 'Sign in with Microsoft';

  return (
    <div className="auth-page">
      {/* Decorative background shapes */}
      <div className="auth-orb one" />
      <div className="auth-orb two" />

      <div className="auth-center">
        <div className="auth-card">
          <div className="auth-mark">S</div>
          <div className="auth-copy">
              <span>MAISON MTL · MICROSOFT FABRIC DEMO</span>
              <h1>MTL Retail IQ</h1>
              <p>
                Sales, inventory, ML forecasts and low-stock alerts for Quebec stores, an embedded bilingual Fabric Data Agent, and reorder requests — on synthetic, illustrative data.
              </p>
            </div>

            <button
              type="button"
              onClick={handleSignIn}
              disabled={isLoading}
              className="microsoft-button"
            >
              {msLogo}
              {buttonLabel}
            </button>

            {(error || authError) && (
              <p role="alert" className="auth-error">{error || authError}</p>
            )}
        </div>
      </div>
    </div>
  );
}
