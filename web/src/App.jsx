import React, { useState } from 'react';
import Plot from 'react-plotly.js';
import { Settings, Play, Activity, AlertCircle, ArrowRight } from 'lucide-react';
import { useMarketData } from './hooks/useMarketData';
import { useForecastStream } from './hooks/useForecastStream';
import './index.css';

function App() {
  const [ticker, setTicker] = useState('RELIANCE.NS');
  const [asOf, setAsOf] = useState('2025-06-02');
  const [debateEnabled, setDebateEnabled] = useState(true);

  const { data, loading, error: dataError } = useMarketData(ticker, asOf);
  const { isRunning, progress, logs, debate, forecast, error: streamError, startForecast } = useForecastStream();

  const handleRun = () => {
    startForecast(ticker, asOf, debateEnabled, []);
  };

  const formatCurrency = (val) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(val);

  const renderChart = () => {
    if (!data?.price?.candles) return null;
    const candles = data.price.candles;
    const x = candles.map(c => c.date);
    const close = candles.map(c => c.close);
    const high = candles.map(c => c.high);
    const low = candles.map(c => c.low);
    const open = candles.map(c => c.open);

    const isDarkMode = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const gridColor = isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
    const textColor = isDarkMode ? '#fafafa' : '#18181b';

    return (
      <div className="panel" style={{ padding: '24px' }}>
        <h3 style={{ marginBottom: '16px', fontSize: '1.1rem', fontWeight: 600 }}>Market Trajectory</h3>
        <Plot
          data={[
            {
              x, close, decreasing: {line: {color: '#ef4444'}}, high, increasing: {line: {color: '#10b981'}},
              line: {color: 'rgba(31,119,180,1)'}, low, open, type: 'candlestick', xaxis: 'x', yaxis: 'y'
            }
          ]}
          layout={{
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { color: textColor, family: 'Inter' },
            margin: { t: 10, l: 40, r: 10, b: 30 },
            xaxis: { rangeslider: { visible: false }, gridcolor: gridColor },
            yaxis: { gridcolor: gridColor },
            height: 350
          }}
          useResizeHandler={true}
          style={{ width: "100%", height: "100%" }}
        />
      </div>
    );
  };

  return (
    <div id="root">
      <aside className="sidebar">
        <h1>
          <div style={{ width: 24, height: 24, borderRadius: 6, background: 'var(--text-main)' }}></div>
          Forecaster
        </h1>
        
        <div className="sidebar-section" style={{ marginTop: '24px' }}>
          <h3>Configuration</h3>
          
          <div className="input-group">
            <label>NSE Symbol</label>
            <input type="text" className="input-control" value={ticker} onChange={(e) => setTicker(e.target.value)} />
          </div>

          <div className="input-group">
            <label>Cutoff Date</label>
            <input type="date" className="input-control" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </div>

          <div className="input-group" style={{ marginTop: '8px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <input type="checkbox" checked={debateEnabled} onChange={(e) => setDebateEnabled(e.target.checked)} />
              Enable Adversarial Debate
            </label>
          </div>
        </div>

        <div style={{ flex: 1 }}></div>

        <button className="btn-primary" onClick={handleRun} disabled={isRunning || loading}>
          {isRunning ? 'Processing...' : 'Run Forecast'} <ArrowRight size={16} />
        </button>
      </aside>

      <main className="dashboard-main">
        <div className="dashboard-header">
          <h2>Overview: {ticker}</h2>
          <p>Analyzing market data up to {asOf}</p>
        </div>

        {dataError && <div style={{ color: 'var(--danger)', padding: 16, background: 'var(--danger-bg)', borderRadius: 8 }}>{dataError}</div>}
        {streamError && <div style={{ color: 'var(--danger)', padding: 16, background: 'var(--danger-bg)', borderRadius: 8 }}>{streamError}</div>}

        {data && (
          <div className="metric-grid">
            <div className="panel metric-card">
              <span className="metric-label">Last Close</span>
              <span className="metric-value">{formatCurrency(data.evidence.last_close)}</span>
            </div>
            <div className="panel metric-card">
              <span className="metric-label">RSI (14)</span>
              <span className="metric-value">{data.evidence.indicators?.rsi_14?.value || 'N/A'}</span>
            </div>
            <div className="panel metric-card">
              <span className="metric-label">MACD Bias</span>
              <span className="metric-value">{data.evidence.indicators?.macd?.bias || 'N/A'}</span>
            </div>
            <div className="panel metric-card">
              <span className="metric-label">NIFTY 50 (21d)</span>
              <span className="metric-value">{data.evidence.benchmark?.return_21d_pct || 'N/A'}%</span>
            </div>
          </div>
        )}

        {renderChart()}

        <div className="two-col-grid">
          <div className="panel" style={{ padding: '24px' }}>
            <h3 style={{ marginBottom: '16px', fontSize: '1.1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity size={18} className={isRunning ? 'running-icon' : ''} /> Pipeline Activity
            </h3>
            <div className="progress-bar-container">
              <div className="progress-bar" style={{ width: `${progress}%` }}></div>
            </div>
            <div className="log-container">
              {logs.length === 0 && <span>Ready.</span>}
              {logs.map((log, i) => (
                <div key={i} className={`log-item ${log.includes('[DONE]') ? 'done' : 'running'}`}>
                  {log.replace('[DONE] ', '').replace('[RUNNING] ', '')}
                </div>
              ))}
            </div>
          </div>

          <div className="panel" style={{ padding: '24px' }}>
            <h3 style={{ marginBottom: '16px', fontSize: '1.1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertCircle size={18} /> Context Highlights
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {data?.evidence?.news?.headlines?.length > 0 ? (
                data.evidence.news.headlines.slice(0, 4).map((h, i) => (
                  <div key={i} style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                    <strong style={{ color: 'var(--text-main)', marginRight: '6px' }}>{h.date}</strong>
                    {h.title}
                  </div>
                ))
              ) : (
                <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>No recent news found before cutoff.</span>
              )}
            </div>
          </div>
        </div>

        {debate && (
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '20px' }}>Debate Analysis</h3>
            <div className="two-col-grid">
              {debate.map((turn, i) => (
                <div key={i} className={`panel debate-card ${turn.position}`}>
                  <h4>Round {turn.round_number}: {turn.position === 'bull' ? 'Bull' : 'Bear'}</h4>
                  <p style={{ fontWeight: 500 }}>Target: {formatCurrency(turn.target_inr)} &middot; Confidence: {(turn.confidence * 100).toFixed(0)}%</p>
                  {turn.rebuttal && <p style={{ fontStyle: 'italic', color: 'var(--text-muted)', marginTop: 8 }}>"{turn.rebuttal}"</p>}
                  <ul style={{ paddingLeft: '20px', marginTop: '12px', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                    {turn.points.map((p, idx) => <li key={idx} style={{ marginBottom: '6px' }}>{p}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}

        {forecast && (
          <div className="panel forecast-result">
            <p style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.05em' }}>
              Final System Output
            </p>
            <div className={`forecast-signal ${forecast.signal.toLowerCase()}`}>
              {forecast.signal}
            </div>
            <div className="forecast-target">
              Target Range: {formatCurrency(forecast.target_low_inr)} &mdash; {formatCurrency(forecast.target_high_inr)}
            </div>
            
            <div style={{ marginTop: '24px', background: 'var(--bg-sidebar)', padding: '24px', borderRadius: 'var(--radius-md)' }}>
              <h4 style={{ marginBottom: '12px', fontSize: '1rem' }}>Rationale</h4>
              <p style={{ lineHeight: 1.6, color: 'var(--text-muted)', fontSize: '0.95rem' }}>{forecast.reasoning}</p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
