import React, { useState } from 'react';
import Plot from 'react-plotly.js';
import { Play, ShieldCheck, TrendingUp, Loader2 } from 'lucide-react';
import { useMarketData } from '../hooks/useMarketData';
import { useForecastStream } from '../hooks/useForecastStream';

const PRESETS = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'SBIN.NS', 'MARUTI.NS'];
const inr = (v) => (v == null || isNaN(v) ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(v));
const dark = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches;

export default function Forecast() {
  const [ticker, setTicker] = useState('RELIANCE.NS');
  const [asOf, setAsOf] = useState('2025-06-02');
  const [debateOn, setDebateOn] = useState(true);
  const { data, loading, error: dataErr } = useMarketData(ticker, asOf);
  const { isRunning, progress, logs, debate, forecast, error: streamErr, startForecast } = useForecastStream();
  const ev = data?.evidence;
  const candles = data?.price?.candles;
  const total = debateOn ? 7 : 6;
  const done = Math.round((progress / 100) * total);
  const fg = dark() ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.06)';
  const sig = forecast?.signal?.toLowerCase();

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
        <div className="note"><ShieldCheck size={13} style={{ verticalAlign: -2 }} /> Every data source is capped at the as-of date in code, not in the prompt. Live forecasts are demonstrations; research claims come only from the evaluation harness.</div>
      </aside>

      <main className="forecast-main">
        <div className="head">
          <div><h2>{ticker}</h2><span>Evidence as of {asOf}</span></div>
          <span className="badge"><ShieldCheck size={14} /> No data after {asOf}</span>
        </div>

        {(dataErr || streamErr) && <div className="err">{dataErr || streamErr}</div>}

        {ev && (
          <div className="kpis">
            <div className="kpi"><small>Last close</small><b>{inr(ev.last_close)}</b></div>
            <div className="kpi"><small>RSI (14)</small><b>{ev.indicators?.rsi_14?.value ?? 'N/A'}</b></div>
            <div className="kpi"><small>MACD bias</small><b style={{ textTransform: 'capitalize' }}>{ev.indicators?.macd?.bias ?? 'N/A'}</b></div>
            <div className="kpi"><small>21d vs NIFTY</small><b>{ev.benchmark?.return_21d_pct ?? 'N/A'}%</b></div>
          </div>
        )}

        {candles && (
          <div className="card">
            <h3><TrendingUp size={13} style={{ verticalAlign: -2 }} /> Price history</h3>
            <Plot
              data={[{ type: 'candlestick', x: candles.map((c) => c.date), open: candles.map((c) => c.open), high: candles.map((c) => c.high), low: candles.map((c) => c.low), close: candles.map((c) => c.close), increasing: { line: { color: '#10b981' } }, decreasing: { line: { color: '#ef4444' } } }]}
              layout={{ paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: dark() ? '#e8ecf7' : '#0f172a', family: 'Inter' }, margin: { t: 6, l: 46, r: 8, b: 28 }, height: 330, xaxis: { rangeslider: { visible: false }, gridcolor: fg }, yaxis: { gridcolor: fg } }}
              config={{ displayModeBar: false, responsive: true }} useResizeHandler style={{ width: '100%' }} />
          </div>
        )}
        {loading && !data && <div className="empty">Loading evidence…</div>}

        {(isRunning || logs.length > 0) && (
          <div className="card">
            <h3>Agent pipeline</h3>
            <div className="steps">{Array.from({ length: total }).map((_, i) => <div key={i} className={`step ${i < done ? 'on' : ''}`} />)}</div>
            <div className="log">{logs.map((l, i) => <div key={i} className={l.startsWith('[DONE]') ? 'd' : ''}>{l}</div>)}</div>
          </div>
        )}

        {forecast && (
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

        {debate?.length > 0 && (
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

        {ev?.news?.headlines?.length > 0 && (
          <div className="card news"><h3>Headlines up to {asOf}</h3>{ev.news.headlines.slice(0, 5).map((h, i) => <div key={i}>{h.title || h}</div>)}</div>
        )}
        {!forecast && !isRunning && !candles && !loading && <div className="empty">Pick a ticker and date, then run a forecast.</div>}
      </main>
    </div>
  );
}
