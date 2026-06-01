import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

// Opt-in redesign preview: open with ?ui=next to render the new flat-editorial
// UI (Claude Design handoff). The current production app stays the default so
// nothing regresses while the redesign is wired to the backend.
const useNextUI = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('ui') === 'next';

const App = React.lazy(() => (useNextUI ? import('./redesign/RedesignApp') : import('./App')));

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <React.Suspense fallback={
            <div className="h-screen w-screen bg-background flex items-center justify-center">
                <div className="w-12 h-12 rounded-full border-2 border-zinc-800 border-t-[oklch(74%_0.175_62)] animate-spin" />
            </div>
        }>
            <App />
        </React.Suspense>
    </React.StrictMode>,
);
