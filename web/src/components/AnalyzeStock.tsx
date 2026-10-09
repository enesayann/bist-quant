import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, Search, AlertCircle } from "lucide-react";
import { analyzeStock, normalizeTicker } from "../api/analysis";
import { useAnalysis } from "../api/context";
import { Badge, Button, Card } from "./ui";

export function AnalyzeStock() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const { save } = useAnalysis();
  const navigate = useNavigate();
  useEffect(() => () => active.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (loading) return;
    setError(null);
    try {
      normalizeTicker(ticker);
    } catch (error) {
      setError((error as Error).message);
      return;
    }
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    try {
      const result = await analyzeStock(ticker, controller.signal);
      if (controller.signal.aborted) return;
      save(result);
      navigate(`/stocks/${result.ticker}`);
    } catch (error) {
      if (!controller.signal.aborted) setError((error as Error).message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  return (
    <Card className="analyze-card">
      <div>
        <div className="analyze-title">
          <Search size={19} />
          <h2>Analyze a BIST stock</h2>
          <Badge tone="accent">Research / Paper Trading</Badge>
        </div>
        <p>
          On-demand Daily v1 analysis from completed Yahoo daily candles. No
          orders or notifications.
        </p>
      </div>
      <form onSubmit={submit} className="analyze-form" aria-busy={loading}>
        <label className="search-input">
          <span className="sr-only">BIST ticker to analyze</span>
          <input
            aria-label="BIST ticker to analyze"
            aria-invalid={!!error}
            aria-describedby="analyze-hint"
            autoComplete="off"
            spellCheck={false}
            placeholder="e.g. ASELS"
            maxLength={32}
            value={ticker}
            onChange={(event) => {
              setTicker(event.target.value);
              setError(null);
            }}
            disabled={loading}
          />
        </label>
        <Button variant="accent" type="submit" disabled={loading}>
          {loading ? "Analyzing…" : "Analyze"}
          {!loading && <ArrowUpRight size={15} />}
        </Button>
      </form>
      <div className="analyze-hint" id="analyze-hint">
        {loading ? (
          <span role="status">Retrieving and validating daily data…</span>
        ) : error ? (
          <span className="negative" role="alert">
            <AlertCircle size={14} />
            {error}
          </span>
        ) : (
          <span>
            ASELS and ASELS.IS are both accepted. Results use the API; dashboard
            cards below remain demo.
          </span>
        )}
      </div>
    </Card>
  );
}
