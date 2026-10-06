import React, { useState, useEffect } from 'react';
import { FileText, Loader2, BarChart2 } from 'lucide-react';

export default function Experiments() {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('http://localhost:8000/api/results')
      .then(r => r.json())
      .then(async data => {
        const jsonFiles = data.results.filter(f => f.kind === 'json' && (f.name.startsWith('ablation_') || f.name.startsWith('multiagent') || f.name.startsWith('naive')));
        
        // Fetch content for each json file
        const enriched = await Promise.all(
          jsonFiles.map(async (file) => {
            const res = await fetch(`http://localhost:8000/api/results/${file.name}`);
            const contentData = await res.json();
            return { ...file, data: contentData.content };
          })
        );
        
        // Group by type
        const ablations = enriched.filter(f => f.name.startsWith('ablation_'));
        const systems = enriched.filter(f => !f.name.startsWith('ablation_'));
        
        setResults({ ablations, systems });
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="empty"><Loader2 className="spin" /> Loading experiments...</div>;
  if (error) return <div className="err">Error loading results: {error}</div>;

  const renderAblationTable = (ablationFiles) => {
    if (!ablationFiles || ablationFiles.length === 0) return <div className="empty">No ablation reports found. Run python -m evaluate ablate.</div>;
    
    // Pick the most recent ablation run
    const latest = ablationFiles[0];
    const pairs = latest.data.pairs || [];
    
    return (
      <div className="card" style={{ overflowX: 'auto' }}>
        <h3><BarChart2 size={14} style={{ verticalAlign: -2, marginRight: 4 }} /> Latest Ablation Study ({new Date(latest.modified).toLocaleString()})</h3>
        <table className="exp-table">
          <thead>
            <tr>
              <th>System</th>
              <th>Directional Acc</th>
              <th>vs NIFTY</th>
              <th>MAPE</th>
              <th>Brier Score</th>
              <th>Δ p-value (McNemar)</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p, i) => (
              <tr key={i}>
                <td><b>{p.system_a}</b> vs <b>{p.system_b}</b></td>
                <td>
                  {p.metrics_a.directional_accuracy_pct?.toFixed(1)}% vs {p.metrics_b.directional_accuracy_pct?.toFixed(1)}%
                </td>
                <td>
                  {p.metrics_a.nifty_relative_accuracy_pct?.toFixed(1)}% vs {p.metrics_b.nifty_relative_accuracy_pct?.toFixed(1)}%
                </td>
                <td>
                  {p.metrics_a.mape_pct?.toFixed(1)}% vs {p.metrics_b.mape_pct?.toFixed(1)}%
                </td>
                <td>
                  {p.metrics_a.brier_score?.toFixed(2)} vs {p.metrics_b.brier_score?.toFixed(2)}
                </td>
                <td>
                  {p.statistical_tests.mcnemar_p ? p.statistical_tests.mcnemar_p.toFixed(3) : 'N/A'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderSystemTable = (systemsFiles) => {
    if (!systemsFiles || systemsFiles.length === 0) return null;
    
    // Deduplicate by system name, keeping the latest
    const latestBySystem = {};
    systemsFiles.forEach(f => {
      const sys = f.data.system;
      if (!latestBySystem[sys]) latestBySystem[sys] = f;
    });
    
    const rows = Object.values(latestBySystem).map(f => f.data.summary);
    rows.sort((a, b) => (b.directional_accuracy_pct || 0) - (a.directional_accuracy_pct || 0));

    return (
      <div className="card" style={{ overflowX: 'auto', marginTop: '20px' }}>
        <h3><FileText size={14} style={{ verticalAlign: -2, marginRight: 4 }} /> Independent System Runs (Latest)</h3>
        <table className="exp-table">
          <thead>
            <tr>
              <th>System</th>
              <th>N</th>
              <th>Dir. Acc %</th>
              <th>vs NIFTY %</th>
              <th>MAPE %</th>
              <th>Brier</th>
              <th>Overconf. Gap</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td><b>{r.system}</b></td>
                <td>{r.n_scoreable}</td>
                <td>{r.directional_accuracy_pct?.toFixed(1)}%</td>
                <td>{r.nifty_relative_accuracy_pct?.toFixed(1)}%</td>
                <td>{r.mape_pct?.toFixed(1)}%</td>
                <td>{r.brier_score?.toFixed(2)}</td>
                <td>{r.overconfidence_gap_pts?.toFixed(1)} pts</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="experiments-main">
      <div className="head" style={{ marginBottom: 20 }}>
        <div><h2>Experiments</h2><span>Live results from evaluation harness</span></div>
      </div>
      {renderAblationTable(results.ablations)}
      {renderSystemTable(results.systems)}
    </div>
  );
}
