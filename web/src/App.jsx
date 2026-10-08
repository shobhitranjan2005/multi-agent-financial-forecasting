import React, { useState } from 'react';
import { Sparkles } from 'lucide-react';
import Forecast from './pages/Forecast';
import Experiments from './pages/Experiments';
import './index.css';

// Research tools (experiments, as-of date, debate switch) are hidden from normal
// visitors. Open the app with ?research=1 to show them (e.g. for the viva).
const research = new URLSearchParams(window.location.search).has('research');

export default function App() {
  const [page, setPage] = useState('forecast');
  return (
    <div className="shell">
      <header className="top">
        <div className="brand"><div className="logo"><Sparkles size={18} /></div>Forecaster</div>
        {research && (
          <nav>
            <button className={page === 'forecast' ? 'on' : ''} onClick={() => setPage('forecast')}>Forecast</button>
            <button className={page === 'research' ? 'on' : ''} onClick={() => setPage('research')}>Experiments</button>
          </nav>
        )}
      </header>
      <main>{research && page === 'research' ? <Experiments /> : <Forecast research={research} />}</main>
      <footer>AI-generated research estimate for educational use. Not investment advice. Markets can move against any forecast.</footer>
    </div>
  );
}
