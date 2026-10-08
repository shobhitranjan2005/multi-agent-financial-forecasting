import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import { Search, TrendingUp, TrendingDown, Minus, Check, Loader2, Info } from 'lucide-react';
import { useMarketData } from '../hooks/useMarketData';
import { useForecastStream } from '../hooks/useForecastStream';

const STOCKS = [
  ['RELIANCE', 'Reliance Industries'], ['TCS', 'Tata Consultancy Services'], ['HDFCBANK', 'HDFC Bank'], ['INFY', 'Infosys'],
  ['ICICIBANK', 'ICICI Bank'], ['HINDUNILVR', 'Hindustan Unilever'], ['ITC', 'ITC'], ['SBIN', 'State Bank of India'],
  ['BHARTIARTL', 'Bharti Airtel'], ['KOTAKBANK', 'Kotak Mahindra Bank'], ['LT', 'Larsen & Toubro'], ['AXISBANK', 'Axis Bank'],
  ['ASIANPAINT', 'Asian Paints'], ['MARUTI', 'Maruti Suzuki'], ['SUNPHARMA', 'Sun Pharma'], ['TITAN', 'Titan'],
  ['ULTRACEMCO', 'UltraTech Cement'], ['WIPRO', 'Wipro'], ['NESTLEIND', 'Nestle India'], ['TATASTEEL', 'Tata Steel'],
  ['JSWSTEEL', 'JSW Steel'], ['POWERGRID', 'Power Grid Corp'], ['NTPC', 'NTPC'], ['ONGC', 'ONGC'],
  ['HCLTECH', 'HCL Technologies'], ['TECHM', 'Tech Mahindra'], ['BAJFINANCE', 'Bajaj Finance'], ['CIPLA', 'Cipla'],
  ['DRREDDY', "Dr. Reddy's Labs"]
];
const NAME = Object.fromEntries(STOCKS);
const STEPS = ['Reading price charts', 'Checking company health', 'Scanning the news', 'Reviewing the economy', 'Fact-checking the numbers', 'Bulls and bears debate', 'Making the final call'];
const STEP_KEYS = ['technical', 'fundamental', 'sentiment', 'macro', 'reconcile', 'debate', 'risk_officer'];
const VIEW = { buy: { Icon: TrendingUp, line: 'We expect the price to rise over the next month.' }, sell: { Icon: TrendingDown, line: 'We expect the price to fall over the next month.' }, hold: { Icon: Minus, line: 'We expect little change over the next month.' } };
const inr = (v) => (v == null || isNaN(v) ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(v));
const base = (t) => t.replace(/\.(NS|BO)$/, '');
const rsiWord = (v) => (v == null ? 'Not available' : v < 30 ? 'Cheap (oversold)' : v > 70 ? 'Overheated' : 'Normal');
const trendWord = (b) => (!b ? 'Not available' : /bull|up|positive/i.test(b) ? 'Rising' : /bear|down|negative/i.test(b) ? 'Falling' : 'Flat');
const confWord = (p) => (p >= 70 ? 'High' : p >= 45 ? 'Medium' : 'Low');
const cite = (c) => (typeof c === 'string' ? { text: c } : { text: c.title || c.source || c.label || 'Source', url: c.url || c.link });
const lastWeekday = () => { const d = new Date(); do { d.setDate(d.getDate() - 1); } while ([0, 6].includes(d.getDay())); return d.toLocaleDateString('en-CA'); };

function useDark() {
  const q = window.matchMedia?.('(prefers-color-scheme: dark)');
  const [d, setD] = useState(!!q?.matches);
  useEffect(() => { if (!q) return; const f = (e) => setD(e.matches); q.addEventListener('change', f); return () => q.removeEventListener('change', f); }, []);
  return d;
}

export default function Forecast({ research }) {
  const [ticker, setTicker] = useState('RELIANCE.NS');
  const [q, setQ] = useState('');
  const [asOf, setAsOf] = useState(lastWeekday());
  const [debateOn, setDebateOn] = useState(true);
  const isDark = useDark();
  const [demoForecast, setDemoForecast] = useState(null);
  
  const { data, loading, error: dataErr } = useMarketData(ticker, asOf);
  const { isRunning, progress, stageStatus, logs, debate, forecast: streamForecast, error: streamErr, startForecast } = useForecastStream();

  const forecast = demoForecast || streamForecast;
  const ev = data?.evidence, candles = data?.price?.candles;
  const hits = q.trim() ? STOCKS.filter(([s, n]) => (s + n).toLowerCase().includes(q.trim().toLowerCase())).slice(0, 6) : [];
  const pick = (s) => { setTicker(s.includes('.') ? s : `${s}.NS`); setQ(''); setDemoForecast(null); };
  
  const steps = debateOn ? STEPS : STEPS.filter((_, i) => i !== 5);
  const stepKeys = debateOn ? STEP_KEYS : STEP_KEYS.filter((_, i) => i !== 5);
  const sig = forecast?.signal?.toLowerCase();
  const V = VIEW[sig];
  const grid = isDark ? 'rgba(255,255,255,.07)' : 'rgba(0,0,0,.07)';
  const bulls = (debate || []).filter((t) => t.position === 'bull'), bears = (debate || []).filter((t) => t.position === 'bear');
  const err = dataErr || streamErr;
  const price = ev?.last_close;
  const last = candles?.[candles.length - 1]?.date;
  const proj = forecast && last ? (() => { const e = new Date(last); e.setDate(e.getDate() + 30); return e.toISOString().slice(0, 10); })() : null;

  const handleStartForecast = () => {
    setDemoForecast(null);
    startForecast(ticker, asOf, debateOn, []);
  };

  const loadDemo = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/demo');
      if (!res.ok) throw new Error('Demo not available');
      const data = await res.json();
      setTicker(data.context?.ticker || 'RELIANCE.NS');
      setAsOf(data.context?.as_of || lastWeekday());
      setDemoForecast(data.record?.forecast);
    } catch (e) {
      console.error(e);
      alert('Demo run is not available. Generate it first.');
    }
  };

  const renderError = () => {
    if (!err) return null;
    const strErr = String(err).toLowerCase();
    let msg = "We couldn't complete that. Please check the company name and try again.";
    
    if (strErr.includes('quota') || strErr.includes('rate limit') || strErr.includes('429')) {
      msg = "The analysts are busy, try again in a minute.";
    } else if (strErr.includes('closed') || strErr.includes('no price data')) {
      msg = "The market was closed or no data was available for that date.";
    } else if (strErr.includes('failed to fetch') || strErr.includes('websocket connection error') || strErr.includes('502')) {
      msg = "The backend is offline or unreachable.";
    } else if (strErr.includes('unsupported ticker') || strErr.includes('unsupported market')) {
      msg = "We couldn't find that company. We currently support Indian equities (NSE/BSE).";
    }

    return (
      <div className="err" role="alert">{msg}{research && <small> {String(err)}</small>}
        <button onClick={handleStartForecast}>Try again</button>
      </div>
    );
  };

  return (
    <div className="page">
      <section className="hero">
        <h1>Should you buy, hold or sell?</h1>
        <p>Pick an Indian stock. Our team of AI analysts reviews the price, the company, the news and the economy, then gives a clear view.</p>
        <div className="search">
          <Search size={18} />
          <input aria-label="Search company or symbol" placeholder="Search a company, e.g. Infosys" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && q.trim()) { if (hits.length) pick(hits[0][0]); else pick(q.trim().toUpperCase()); } }} />
          {hits.length > 0 && <ul className="sug">{hits.map(([s, n]) => <li key={s}><button onClick={() => pick(s)}>{n}<small>{s}</small></button></li>)}</ul>}
        </div>
        <div className="chips">{STOCKS.slice(0, 8).map(([s, n]) => <button key={s} className={`chip ${base(ticker) === s ? 'on' : ''}`} onClick={() => pick(s)}>{n}</button>)}</div>
        {research && (
          <div className="rbar">
            <label>As-of date <input type="date" max={new Date().toLocaleDateString('en-CA')} value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
            <label><input type="checkbox" checked={debateOn} onChange={(e) => setDebateOn(e.target.checked)} /> Bull–Bear debate</label>
          </div>
        )}
      </section>

      <div className="titlerow">
        <div><h2>{NAME[base(ticker)] || base(ticker)}</h2><span>{base(ticker)} · NSE</span></div>
        <div>
          <button className="demo-btn" disabled={isRunning} onClick={loadDemo} style={{marginRight: '12px', background: 'transparent', border: '1px solid currentColor', color: 'inherit'}}>
            See a sample forecast
          </button>
          <button className="go" disabled={isRunning} onClick={handleStartForecast}>
            {isRunning ? <><Loader2 size={17} className="spin" /> Analysing…</> : 'Get forecast'}
          </button>
        </div>
      </div>

      {renderError()}

      {loading && !ev && <div className="skel"><i /><i /><i /></div>}
      {ev && (
        <div className="kpis">
          <div className="kpi"><small>Latest price</small><b>{inr(price)}</b></div>
          <div className="kpi"><small>Price momentum</small><b>{rsiWord(ev.indicators?.rsi_14?.value)}</b></div>
          <div className="kpi"><small>Recent trend</small><b>{trendWord(ev.indicators?.macd?.bias)}</b></div>
          <div className="kpi"><small>Vs Nifty 50 (1 month)</small><b>{ev.benchmark?.return_21d_pct != null ? `${ev.benchmark.return_21d_pct > 0 ? '+' : ''}${ev.benchmark.return_21d_pct}%` : '—'}</b></div>
        </div>
      )}
      {candles && (
        <div className="card"><h3>Price history{proj && ' · shaded area = our likely range for the next month'}</h3>
          <Plot data={[{ type: 'candlestick', x: candles.map((c) => c.date), open: candles.map((c) => c.open), high: candles.map((c) => c.high), low: candles.map((c) => c.low), close: candles.map((c) => c.close), increasing: { line: { color: '#10b981' } }, decreasing: { line: { color: '#ef4444' } } }]}
            layout={{ paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: isDark ? '#e8ecf7' : '#0f172a', family: 'Inter' }, margin: { t: 6, l: 46, r: 8, b: 28 }, height: 320, shapes: proj ? [{ type: 'rect', xref: 'x', yref: 'y', x0: last, x1: proj, y0: forecast.target_low_inr, y1: forecast.target_high_inr, fillcolor: 'rgba(99,102,241,.28)', line: { width: 0 } }] : [], xaxis: { rangeslider: { visible: false }, gridcolor: grid, ...(proj ? { range: [candles[Math.max(0, candles.length - 90)].date, proj] } : {}) }, yaxis: { gridcolor: grid } }}
            config={{ displayModeBar: false, responsive: true }} useResizeHandler style={{ width: '100%' }} />
        </div>
      )}

      {(isRunning || logs.length > 0) && (
        <div className="card"><h3>What our analysts are doing</h3>
          <ol className="steps">{steps.map((s, i) => {
            const key = stepKeys[i];
            const isOk = stageStatus?.[key] === 'done';
            const isNow = stageStatus?.[key] === 'running';
            return (
              <li key={s} className={isOk ? 'ok' : isNow ? 'now' : ''}>
                {isOk ? <Check size={16} /> : isNow ? <Loader2 size={16} className="spin" /> : <span className="dot" />}
                {s}
              </li>
            );
          })}</ol>
          {research && <details><summary>Technical log</summary><pre className="log">{logs.join('\n')}</pre></details>}
        </div>
      )}

      {forecast && V && (
        <div className="result">
          <div className={`sig ${sig}`}>
            <V.Icon size={34} aria-hidden="true" />
            <div className="w">{forecast.signal}</div>
            <p>{V.line}</p>
            <div className="rng"><small>Likely price range</small>{inr(forecast.target_low_inr)} – {inr(forecast.target_high_inr)}</div>
            <div className="conf" role="img" aria-label={`Confidence ${forecast.confidence_pct}%`}><i style={{ width: `${forecast.confidence_pct ?? 0}%` }} /></div>
            <small>{confWord(forecast.confidence_pct)} confidence ({forecast.confidence_pct ?? '—'}%)</small>
          </div>
          <div className="card"><h3>Why we think so</h3><p className="reason">{forecast.reasoning}</p>
            {forecast.key_risks?.length > 0 && <><h3 style={{ marginTop: 18 }}>What could go wrong</h3>
              <ul className="risks">{forecast.key_risks.map((r, i) => <li key={i}>{typeof r === 'string' ? r : JSON.stringify(r)}</li>)}</ul></>}
          </div>
        </div>
      )}

      {(bulls.length > 0 || bears.length > 0) && (
        <div className="card"><h3>Both sides of the argument</h3>
          <div className="debate">
            <div className="turn bull"><h4>The case for buying</h4>{bulls.map((t, i) => <ul key={i}>{t.points?.map((p, j) => <li key={j}>{p}</li>)}</ul>)}</div>
            <div className="turn bear"><h4>The case against</h4>{bears.map((t, i) => <ul key={i}>{t.points?.map((p, j) => <li key={j}>{p}</li>)}</ul>)}</div>
          </div>
        </div>
      )}

      {forecast?.citations?.length > 0 && (
        <div className="card"><h3>Where this comes from</h3><ul className="src">{forecast.citations.slice(0, 8).map((c, i) => { const x = cite(c); return <li key={i}>{x.url ? <a href={x.url} target="_blank" rel="noreferrer">{x.text}</a> : x.text}</li>; })}</ul></div>
      )}
      {ev?.news?.headlines?.length > 0 && (
        <div className="card"><h3>Recent news we looked at</h3><ul className="src">{ev.news.headlines.slice(0, 5).map((h, i) => <li key={i}>{h.title || h}</li>)}</ul></div>
      )}
      {!forecast && !isRunning && <p className="hint"><Info size={14} /> Press “Get forecast” and wait about a minute while the analysts work.</p>}
      <footer style={{ marginTop: '3rem', borderTop: '1px solid var(--border)', paddingTop: '1.5rem', textAlign: 'center', opacity: 0.7, fontSize: '0.85rem' }}>
        AI-generated research estimate, not investment advice.
      </footer>
    </div>
  );
}
