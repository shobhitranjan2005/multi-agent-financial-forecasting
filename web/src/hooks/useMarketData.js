import { useState, useEffect } from 'react';

export function useMarketData(ticker, asOf) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ticker || !asOf) return;
    
    let isMounted = true;
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [priceRes, evidenceRes] = await Promise.all([
          fetch(`http://localhost:8000/api/price/${ticker}?as_of=${asOf}&sessions=180`),
          fetch(`http://localhost:8000/api/evidence/${ticker}?as_of=${asOf}&extras=true`)
        ]);

        if (!priceRes.ok) throw new Error(await priceRes.text());
        if (!evidenceRes.ok) throw new Error(await evidenceRes.text());

        const priceData = await priceRes.json();
        const evidenceData = await evidenceRes.json();

        if (isMounted) {
          setData({ price: priceData, evidence: evidenceData });
        }
      } catch (err) {
        if (isMounted) setError(err.message);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchData();

    return () => { isMounted = false; };
  }, [ticker, asOf]);

  return { data, loading, error };
}
