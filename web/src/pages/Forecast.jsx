import React, { useState, useEffect, useRef } from 'react';
import Plot from 'react-plotly.js';
import { Play, ShieldCheck, TrendingUp, Loader2 } from 'lucide-react';
import { useMarketData } from '../hooks/useMarketData';
import { useForecastStream } from '../hooks/useForecastStream';

const PRESETS = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'SBIN.NS', 'MARUTI.NS'];
const inr = (v) => (v == null || isNaN(v) ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(v));
const dark = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches;
const getFutureDateStr = (dateStr, days) => {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
};

const AGENTS = [
  { id: 'technical', name: 'Technical Analyst' },
  { id: 'fundamental', name: 'Fundamental Analyst' },
  { id: 'sentiment', name: 'Sentiment Analyst' },
  { id: 'macro', name: 'Macro Analyst' },
  { id: 'debate', name: 'Adversarial Debate Engine' },
  { id: 'final', name: 'Chief Risk Officer' }
];

export default function Forecast() {
  const [ticker, setTicker] = useState('RELIANCE.NS');
  
  // Format today's date as YYYY-MM-DD
  const today = new Date().toLocaleDateString('en-CA');
  const [asOf, setAsOf] = useState(today);
  
  const [debateOn, setDebateOn] = useState(true);
  const [activeAgent, setActiveAgent] = useState(null);
  const terminalRef = useRef(null);

  const { data, loading, error: dataErr } = useMarketData(ticker, asOf);
  const { isRunning, progress, logs, debate, forecast, error: streamErr, startForecast } = useForecastStream();
  const ev = data?.evidence;
  const candles = data?.price?.candles;
  const fg = dark() ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.06)';
  const sig = forecast?.signal?.toLowerCase();

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  const getAgentState = (agentId) => {
    const searchId = agentId === 'final' ? 'final' : agentId;
    const doneLog = logs.find(l => l.toLowerCase().includes(`[done] ${searchId}`));
    if (doneLog) return 'done';
    const runningLog = logs.find(l => l.toLowerCase().includes(`[running] ${searchId}`));
    if (runningLog) return 'running';
    return 'waiting';
  };

  const terminalLogs = logs.filter(l => {
    if (!activeAgent) return true;
    return l.toLowerCase().includes(activeAgent);
  });

  const targetShapes = forecast ? [{
    type: 'rect',
    xref: 'x', yref: 'y',
    x0: asOf,
    x1: getFutureDateStr(asOf, 30),
    y0: forecast.target_low_inr,
    y1: forecast.target_high_inr,
    fillcolor: 'rgba(99, 102, 241, 0.15)',
    line: { color: 'rgba(99, 102, 241, 0.5)', width: 1, dash: 'dot' }
  }] : [];

  return (
    <div className="forecast-layout">
      <aside className="side">
        <label>Ticker</label>
        <input type="text" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
        <div className="chips">{PRESETS.map((p) => <button key={p} className="chip" onClick={() => setTicker(p)}>{p.replace('.NS', '')}</button>)}</div>

        <label>As-of date</label>
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />

        <div className="switch" onClick={() => setDebateOn(!debateOn)}>
          <div>Bull–Bear debate<small>Turn off for the ablation</small></div>
          <div className={`tog ${debateOn ? 'on' : ''}`} />
        </div>

        <button className="run" disabled={isRunning} onClick={() => startForecast(ticker, asOf, debateOn, [])}>
          {isRunning ? <><Loader2 size={17} className="spin" /> Analysing…</> : <><Play size={16} /> Run forecast</>}
        </button>

        <div className="agent-matrix">
          <h4>Agent Command Center</h4>
          {AGENTS.filter(a => debateOn || a.id !== 'debate').map(agent => (
            <div 
              key={agent.id} 
              className={`agent-status ${getAgentState(agent.id)} ${activeAgent === agent.id ? 'active' : ''}`} 
              onClick={() => setActiveAgent(activeAgent === agent.id ? null : agent.id)}
            >
              <span className="status-indicator"></span>
              {agent.name}
            </div>
          ))}
        </div>
      </aside>

      <main className="forecast-main">
        <div className="head">
          <div><h2>{ticker}</h2><span>Evidence as of {asOf}</span></div>
          <span className="badge"><ShieldCheck size={14} /> No data after {asOf}</span>
        </div>

        {(dataErr || streamErr) && <div className="err">{dataErr || streamErr}</div>}

        {ev && (!activeAgent || activeAgent !== 'sentiment') && (
          <div className="kpis">
            <div className="kpi"><small>Last close</small><b>{inr(ev.last_close)}</b></div>
            <div className="kpi"><small>RSI (14)</small><b>{ev.indicators?.rsi_14?.value ?? 'N/A'}</b></div>
            <div className="kpi"><small>MACD bias</small><b style={{ textTransform: 'capitalize' }}>{ev.indicators?.macd?.bias ?? 'N/A'}</b></div>
            <div className="kpi"><small>21d vs NIFTY</small><b>{ev.benchmark?.return_21d_pct ?? 'N/A'}%</b></div>
          </div>
        )}

        {candles && (!activeAgent || activeAgent === 'technical' || activeAgent === 'final') && (
          <div className="card">
            <h3><TrendingUp size={13} style={{ verticalAlign: -2 }} /> Price history {forecast && '(+ 21d Target Projection)'}</h3>
            <Plot
              data={[{ type: 'candlestick', x: candles.map((c) => c.date), open: candles.map((c) => c.open), high: candles.map((c) => c.high), low: candles.map((c) => c.low), close: candles.map((c) => c.close), increasing: { line: { color: '#10b981' } }, decreasing: { line: { color: '#ef4444' } } }]}
              layout={{ shapes: targetShapes, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: dark() ? '#e8ecf7' : '#0f172a', family: 'Inter' }, margin: { t: 6, l: 46, r: 8, b: 28 }, height: 330, xaxis: { rangeslider: { visible: false }, gridcolor: fg }, yaxis: { gridcolor: fg } }}
              config={{ displayModeBar: false, responsive: true }} useResizeHandler style={{ width: '100%' }} />
          </div>
        )}
        
        {loading && !data && <div className="empty">Loading evidence…</div>}

        {(isRunning || logs.length > 0) && (
          <div className="terminal-ui card">
            <div className="terminal-header">
              <div className="term-dots"><i className="r"></i><i className="y"></i><i className="g"></i></div>
              <span>Live Reasoning Trace {activeAgent ? `[FILTERED: ${activeAgent.toUpperCase()}]` : ''}</span>
            </div>
            <div className="terminal-body" ref={terminalRef}>
              {terminalLogs.map((log, i) => {
                const match = log.match(/\[(.*?)\] (.*?) - (.*)/) || log.match(/\[(.*?)\] (.*?)\.\.\./);
                if (match) {
                  const [, status, agent, msg] = match;
                  return (
                    <div key={i} className={`term-log ${status.toLowerCase()}`}>
                      <span className="term-agent">[{agent.toUpperCase()}]:</span> {msg || 'Processing...'}
                    </div>
                  );
                }
                return <div key={i} className="term-log">{log}</div>;
              })}
            </div>
          </div>
        )}

        {forecast && (!activeAgent || activeAgent === 'final') && (
          <div className="result">
            <div className={`sig ${sig}`}>
              <div className="w">{forecast.signal}</div>
              <div className="rng">{inr(forecast.target_low_inr)} – {inr(forecast.target_high_inr)}</div>
              <div className="conf"><i style={{ width: `${forecast.confidence_pct ?? 0}%` }} /></div>
              <small>Confidence {forecast.confidence_pct ?? '—'}% · expects {forecast.expected_direction}</small>
            </div>
            <div className="card">
              <h3>Reasoning</h3>
              <p className="reason">{forecast.reasoning}</p>
              {forecast.key_risks?.length > 0 && <div className="risks">{forecast.key_risks.map((r, i) => <span key={i} className="risk">{typeof r === 'string' ? r : JSON.stringify(r)}</span>)}</div>}
            </div>
          </div>
        )}

        {debate?.length > 0 && (!activeAgent || activeAgent === 'debate') && (
          <div className="card">
            <h3>Bull vs Bear debate</h3>
            <div className="debate">
              {debate.map((t, i) => (
                <div key={i} className={`turn ${t.position}`}>
                  <h4>Round {t.round_number} · {t.position === 'bull' ? '🐂 Bull' : '🐻 Bear'}</h4>
                  <ul>{t.points?.map((p, j) => <li key={j}>{p}</li>)}</ul>
                </div>
              ))}
            </div>
          </div>
        )}

        {ev?.news?.headlines?.length > 0 && (!activeAgent || activeAgent === 'sentiment') && (
          <div className="card news"><h3>Headlines up to {asOf}</h3>{ev.news.headlines.slice(0, 5).map((h, i) => <div key={i}>{h.title || h}</div>)}</div>
        )}
        {!forecast && !isRunning && !candles && !loading && <div className="empty">Pick a ticker and date, then run a forecast.</div>}
      </main>
    </div>
  );
}
