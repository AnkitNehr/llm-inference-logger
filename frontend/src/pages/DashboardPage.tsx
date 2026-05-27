import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getErrors, getLatency, getOverview, getThroughput } from "../api";

export default function DashboardPage() {
  const [overview, setOverview] = useState<any>(null);
  const [latency, setLatency] = useState<any>({ points: [] });
  const [throughput, setThroughput] = useState<any>({ points: [] });
  const [errors, setErrors] = useState<any>({ breakdown: [] });

  async function load() {
    const [o, l, t, e] = await Promise.all([getOverview(), getLatency(), getThroughput(), getErrors()]);
    setOverview(o); setLatency(l); setThroughput(t); setErrors(e);
  }
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const latencyData = (latency.points || []).map((p: any) => ({
    t: new Date(p.bucket).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    p50: Math.round(p.p50), p95: Math.round(p.p95),
  }));
  const throughputData = (throughput.points || []).map((p: any) => ({
    t: new Date(p.bucket).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    requests: p.requests,
  }));

  return (
    <div className="dashboard">
      <h2>Inference Dashboard</h2>
      <div className="cards">
        <Card label="Requests (24h)" value={overview?.total_requests ?? "—"} />
        <Card label="Success" value={overview?.success_count ?? "—"} />
        <Card label="Errors" value={overview?.error_count ?? "—"} />
        <Card label="Cancelled" value={overview?.cancelled_count ?? "—"} />
        <Card label="Avg latency (ms)" value={overview ? Math.round(overview.avg_latency_ms) : "—"} />
        <Card label="p95 latency (ms)" value={overview ? Math.round(overview.p95_latency_ms) : "—"} />
        <Card label="Total tokens" value={overview?.total_tokens ?? "—"} />
      </div>

      <div className="chart-card">
        <h3>Latency (p50 / p95, ms)</h3>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={latencyData}>
            <CartesianGrid stroke="#1f2937" />
            <XAxis dataKey="t" stroke="#6b7280" />
            <YAxis stroke="#6b7280" />
            <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #1f2937" }} />
            <Legend />
            <Line type="monotone" dataKey="p50" stroke="#60a5fa" dot={false} />
            <Line type="monotone" dataKey="p95" stroke="#f59e0b" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-card">
        <h3>Throughput (requests / {throughput.bucket_size || "min"})</h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={throughputData}>
            <CartesianGrid stroke="#1f2937" />
            <XAxis dataKey="t" stroke="#6b7280" />
            <YAxis stroke="#6b7280" />
            <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #1f2937" }} />
            <Bar dataKey="requests" fill="#22c55e" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-card">
        <h3>Errors by type</h3>
        {errors.breakdown.length === 0 && <div style={{ color: "#6b7280" }}>No errors in window.</div>}
        {errors.breakdown.length > 0 && (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={errors.breakdown}>
              <CartesianGrid stroke="#1f2937" />
              <XAxis dataKey="error_type" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #1f2937" }} />
              <Bar dataKey="count" fill="#dc2626" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}
