import { useState, useCallback, useRef } from 'react';

export function useForecastStream() {
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState([]);
  const [debate, setDebate] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState(null);
  const ws = useRef(null);

  const startForecast = useCallback((ticker, asOf, debateEnabled, drop) => {
    setIsRunning(true);
    setProgress(0);
    setLogs([]);
    setDebate(null);
    setForecast(null);
    setError(null);

    const wsUrl = `ws://localhost:8000/api/stream/${ticker}`;
    ws.current = new WebSocket(wsUrl);

    let doneStages = 0;
    const totalStages = debateEnabled ? 7 : 6;

    ws.current.onopen = () => {
      ws.current.send(JSON.stringify({
        as_of: asOf,
        debate: debateEnabled,
        drop: drop
      }));
    };

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.event === 'stage') {
        const label = data.label || data.stage;
        if (data.status === 'done') {
          doneStages += 1;
          setProgress((doneStages / totalStages) * 100);
          setLogs(prev => [...prev, `[DONE] ${label} - ${data.detail} (${data.elapsed}s)`]);
        } else {
          setLogs(prev => [...prev, `[RUNNING] ${label}...`]);
        }
      } else if (data.event === 'done') {
        setProgress(100);
        setIsRunning(false);
        setDebate(data.debate);
        setForecast(data.record?.forecast);
      } else if (data.event === 'error') {
        setError(data.detail);
        setIsRunning(false);
      }
    };

    ws.current.onerror = () => {
      setError('WebSocket connection error');
      setIsRunning(false);
    };

    ws.current.onclose = () => {
      setIsRunning(false);
    };
  }, []);

  const stopForecast = useCallback(() => {
    if (ws.current) {
      ws.current.close();
    }
  }, []);

  return { isRunning, progress, logs, debate, forecast, error, startForecast, stopForecast };
}
