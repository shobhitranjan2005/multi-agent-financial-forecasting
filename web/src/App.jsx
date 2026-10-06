import React, { useState } from 'react';
import { Sparkles, Activity, FlaskConical } from 'lucide-react';
import Forecast from './pages/Forecast';
import Experiments from './pages/Experiments';
import './index.css';

export default function App() {
  const [activeTab, setActiveTab] = useState('forecast');

  return (
    <div className="app-container">
      <nav className="top-nav">
        <div className="brand"><div className="logo"><Sparkles size={18} /></div>Forecaster</div>
        <div className="nav-links">
          <button className={`nav-link ${activeTab === 'forecast' ? 'active' : ''}`} onClick={() => setActiveTab('forecast')}>
            <Activity size={16} /> Live Forecast
          </button>
          <button className={`nav-link ${activeTab === 'experiments' ? 'active' : ''}`} onClick={() => setActiveTab('experiments')}>
            <FlaskConical size={16} /> Experiments
          </button>
        </div>
      </nav>
      
      <div className="page-content">
        {activeTab === 'forecast' && <Forecast />}
        {activeTab === 'experiments' && <Experiments />}
      </div>
    </div>
  );
}
