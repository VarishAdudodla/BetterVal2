import { useState, useRef } from "react";
import "./App.css";

const API_BASE = "https://betterval2-production.up.railway.appp";

function formatCurrency(val, compact = false) {
  if (!val && val !== 0) return "—";
  if (compact) {
    if (Math.abs(val) >= 1e12) return `$${(val / 1e12).toFixed(2)}T`;
    if (Math.abs(val) >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
    if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(1)}M`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(val);
}

function formatPct(val) {
  if (val == null) return "—";
  return `${(val * 100).toFixed(1)}%`;
}

function Spinner() {
  return <span className="spinner" />;
}

export default function App() {
  const fileInputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [step, setStep] = useState(1);

  const [parsed, setParsed] = useState(null);
  const [assumptions, setAssumptions] = useState(null);
  const [result, setResult] = useState(null);

  const [description, setDescription] = useState("");
  const [industry, setIndustry] = useState("");

  const [loadingPdf, setLoadingPdf] = useState(false);
  const [loadingAssumptions, setLoadingAssumptions] = useState(false);
  const [loadingValuation, setLoadingValuation] = useState(false);

  const [errorPdf, setErrorPdf] = useState(null);
  const [errorAssumptions, setErrorAssumptions] = useState(null);
  const [errorValuation, setErrorValuation] = useState(null);

  const handleFileDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer?.files?.[0] || e.target.files?.[0];
    if (f && f.type === "application/pdf") {
      setFile(f);
      setErrorPdf(null);
    }
  };

  const handleParsePdf = async () => {
    if (!file) return;
    setLoadingPdf(true);
    setErrorPdf(null);
    setParsed(null);
    setAssumptions(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/parse-pdf`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to parse PDF");
      setParsed(data.parsed);
      setStep(2);
    } catch (e) {
      setErrorPdf(e.message);
    } finally {
      setLoadingPdf(false);
    }
  };

  const handleGenerateAssumptions = async () => {
    if (!parsed) return;
    setLoadingAssumptions(true);
    setErrorAssumptions(null);
    setAssumptions(null);
    setResult(null);

    try {
      const res = await fetch(`${API_BASE}/generate-assumptions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parsed, description, industry }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to generate assumptions");
      setAssumptions(data.assumptions);
      setStep(3);
    } catch (e) {
      setErrorAssumptions(e.message);
    } finally {
      setLoadingAssumptions(false);
    }
  };

  const handleRunValuation = async () => {
    if (!parsed || !assumptions) return;
    setLoadingValuation(true);
    setErrorValuation(null);
    setResult(null);

    try {
      const res = await fetch(`${API_BASE}/value`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parsed, assumptions }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Valuation failed");
      setResult(data);
      setStep(4);
    } catch (e) {
      setErrorValuation(e.message);
    } finally {
      setLoadingValuation(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setParsed(null);
    setAssumptions(null);
    setResult(null);
    setDescription("");
    setIndustry("");
    setStep(1);
    setErrorPdf(null);
    setErrorAssumptions(null);
    setErrorValuation(null);
  };

  const stepDone = (s) => step > s;
  const stepActive = (s) => step === s;

  const stepClass = (n) => {
    if (stepDone(n)) return "step step--done";
    if (stepActive(n)) return "step step--active";
    return "step step--idle";
  };

  const stepNumClass = (n) => {
    if (stepDone(n)) return "step-num step-num--done";
    if (stepActive(n)) return "step-num step-num--active";
    return "step-num step-num--idle";
  };

  const uploadZoneClass = () => {
    if (dragging) return "upload-zone upload-zone--dragging";
    if (file) return "upload-zone upload-zone--has-file";
    return "upload-zone";
  };

  const STEPS = [
    ["Upload PDF", 1],
    ["Financials", 2],
    ["Assumptions", 3],
    ["Result", 4],
  ];

  return (
    <div className="app">
      {/* Nav */}
      <nav className="nav">
        <div className="nav-logo">
          <div className="logo-mark">B</div>
          BetterVal
        </div>
        <div className="nav-right">
          <span className="status-dot" />
          API connected
        </div>
      </nav>

      <main className="main">
        {/* Header */}
        <div className="page-header">
          <h1 className="page-title">DCF Valuation</h1>
          <p className="page-subtitle">
            Upload a 10-K or 10-Q to extract financials and generate an intrinsic value estimate.
          </p>
        </div>

        {/* Steps */}
        <div className="step-row">
          {STEPS.map(([label, n], i) => (
            <div key={n} style={{ display: "contents" }}>
              <div className={stepClass(n)}>
                <div className={stepNumClass(n)}>
                  {stepDone(n) ? "✓" : n}
                </div>
                {label}
              </div>
              {i < STEPS.length - 1 && <div className="step-divider" />}
            </div>
          ))}
        </div>

        {/* Step 1 — Upload */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">
              <div className="card-icon">📄</div>
              Upload Filing
            </div>
            {step > 1 && <span className="pill pill--green">✓ Done</span>}
          </div>
          <div className="card-body">
            <div
              className={uploadZoneClass()}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleFileDrop}
            >
              <span className="upload-icon">{file ? "✅" : "📂"}</span>
              <div className="upload-label">
                {file ? file.name : "Drop your 10-K or 10-Q PDF here"}
              </div>
              <div className="upload-sub">
                {file
                  ? `${(file.size / 1024 / 1024).toFixed(2)} MB — click to replace`
                  : "or click to browse — PDF only, max 10 MB"}
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              style={{ display: "none" }}
              onChange={handleFileDrop}
            />
            {errorPdf && <div className="alert alert--error">{errorPdf}</div>}
            <div className="actions-right" style={{ marginTop: 14 }}>
              <button
                className="btn btn--primary"
                disabled={!file || loadingPdf}
                onClick={handleParsePdf}
              >
                {loadingPdf ? <><Spinner /> Extracting…</> : "Extract Financials →"}
              </button>
            </div>
          </div>
        </div>

        {/* Step 2 — Parsed financials */}
        {parsed && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <div className="card-icon">📊</div>
                Extracted Financials
              </div>
              {step > 2 && <span className="pill pill--green">✓ Done</span>}
            </div>
            <div className="card-body">
              <div className="metrics-grid">
                <div className="metric-card">
                  <div className="metric-label">Revenue (Latest)</div>
                  <div className="metric-value">{formatCurrency(parsed.revenue?.[0], true)}</div>
                  {parsed.revenueGrowth?.[0] != null && (
                    <div className="metric-sub">
                      YoY growth:{" "}
                      <strong className={parsed.revenueGrowth[0] >= 0 ? "revenue-growth--positive" : "revenue-growth--negative"}>
                        {formatPct(parsed.revenueGrowth[0])}
                      </strong>
                    </div>
                  )}
                </div>
                <div className="metric-card">
                  <div className="metric-label">Operating Margin</div>
                  <div className="metric-value">{formatPct(parsed.operatingMargin?.[0])}</div>
                  <div className="metric-sub">most recent period</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Tax Rate</div>
                  <div className="metric-value">{formatPct(parsed.taxRate?.[0])}</div>
                  <div className="metric-sub">effective rate</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Cash</div>
                  <div className="metric-value">{formatCurrency(parsed.cash, true)}</div>
                  <div className="metric-sub">& equivalents</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Total Debt</div>
                  <div className="metric-value">{formatCurrency(parsed.totalDebt, true)}</div>
                  <div className="metric-sub">ST + LT debt</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Shares Outstanding</div>
                  <div className="metric-value">
                    {parsed.sharesOutstanding
                      ? `${(parsed.sharesOutstanding / 1e9).toFixed(2)}B`
                      : "—"}
                  </div>
                  <div className="metric-sub">diluted</div>
                </div>
              </div>

              <hr className="divider" />

              <div className="generate-header">
                <div className="generate-title">Generate Assumptions</div>
                <p className="generate-sub">
                  Provide context so the model can produce more accurate DCF inputs.
                </p>
              </div>

              <div className="row-2col">
                <div className="input-group">
                  <label className="label">Industry</label>
                  <input
                    className="input"
                    placeholder="e.g. Semiconductors"
                    value={industry}
                    onChange={(e) => setIndustry(e.target.value)}
                  />
                </div>
                <div className="input-group">
                  <label className="label">Company description (optional)</label>
                  <input
                    className="input"
                    placeholder="e.g. Fabless chip designer, B2B SaaS…"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
              </div>

              {errorAssumptions && (
                <div className="alert alert--error">{errorAssumptions}</div>
              )}

              <div className="actions-right">
                <button
                  className="btn btn--primary"
                  disabled={loadingAssumptions}
                  onClick={handleGenerateAssumptions}
                >
                  {loadingAssumptions ? <><Spinner /> Generating…</> : "Generate Assumptions →"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 3 — Assumptions */}
        {assumptions && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <div className="card-icon">🔮</div>
                DCF Assumptions
              </div>
              {step > 3 && <span className="pill pill--green">✓ Done</span>}
            </div>
            <div className="card-body">
              <div className="assumption-grid">
                {[
                  ["Short-term Revenue Growth", formatPct(assumptions.sterm_rev_g), "Years 1–5"],
                  ["Long-term Revenue Growth", formatPct(assumptions.lterm_rev_g), "Years 6–10"],
                  ["Target Operating Margin", formatPct(assumptions.ending_op_marg), "by year 10"],
                  ["Reinvestment Rate", formatPct(assumptions.reinvestment_r), "fraction of NOPAT"],
                ].map(([label, value, sub]) => (
                  <div key={label} className="assumption-item">
                    <div className="metric-label">{label}</div>
                    <div className="metric-value" style={{ fontSize: 22 }}>{value}</div>
                    <div className="metric-sub">{sub}</div>
                  </div>
                ))}
              </div>

              <div className="industry-tag">
                <strong>Industry:</strong> {assumptions.industry}
              </div>

              {errorValuation && (
                <div className="alert alert--error">{errorValuation}</div>
              )}

              <div className="actions-right--mt">
                <button
                  className="btn btn--primary"
                  disabled={loadingValuation}
                  onClick={handleRunValuation}
                >
                  {loadingValuation ? <><Spinner /> Calculating…</> : "Run Valuation →"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 4 — Result */}
        {result && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <div className="card-icon card-icon--result">💎</div>
                Intrinsic Value
              </div>
              <span className="pill pill--blue">DCF Model</span>
            </div>
            <div className="card-body">
              <div className="result-banner">
                <div>
                  <div className="result-label">Equity Value Per Share</div>
                  <div className="result-value">{formatCurrency(result.equity_value_per_share)}</div>
                  <div className="result-sub">based on 10-year DCF projection</div>
                </div>
              </div>

              <div className="result-2col">
                <div className="metric-card">
                  <div className="metric-label">Enterprise Value</div>
                  <div className="metric-value">{formatCurrency(result.enterprise_value, true)}</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Equity Value</div>
                  <div className="metric-value">{formatCurrency(result.equity_value, true)}</div>
                  <div className="metric-sub">EV − debt + cash</div>
                </div>
              </div>

              <div className="disclaimer">
                ⚠️ For informational purposes only. This valuation is model-dependent and subject
                to significant estimation error. Not investment advice.
              </div>

              <div className="actions-right--mt">
                <button className="btn btn--outline" onClick={handleReset}>
                  ↺ New valuation
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}