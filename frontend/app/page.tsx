"use client";

import { useEffect, useState } from "react";
import type { Alert, Portfolio, Underlying } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const inr = (n: number) =>
  n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const num = (n: number, d = 1) => n.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const tone = (n: number) => (n > 0 ? "pos" : n < 0 ? "neg" : "");

type Status = "connecting" | "live" | "login" | "error";

export default function Home() {
  const [data, setData] = useState<Portfolio | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [error, setError] = useState("");

  useEffect(() => {
    let ws: WebSocket;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      ws = new WebSocket(API.replace(/^http/, "ws") + "/ws/portfolio");
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "portfolio") {
          setData(msg.data);
          setStatus("live");
        } else if (msg.error === "not_logged_in") {
          setStatus("login");
        } else {
          setStatus("error");
          setError(msg.error);
        }
      };
      ws.onclose = () => {
        setStatus((s) => (s === "login" ? s : "connecting"));
        retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      clearTimeout(retry);
      ws.onclose = null;
      ws.close();
    };
  }, []);

  return (
    <main>
      <header className="top">
        <h1>Option Seller</h1>
        <span className={`status ${status}`}>
          {status === "live" && "Live"}
          {status === "connecting" && "Connecting…"}
          {status === "login" && "Not logged in"}
          {status === "error" && `Error: ${error}`}
        </span>
        {status === "login" && (
          <a className="button" href={`${API}/auth/login`}>
            Log in with Kite
          </a>
        )}
      </header>

      {data && (
        <>
          <section className="tiles">
            <Tile label="Total P&L" value={inr(data.totals.pnl)} cls={tone(data.totals.pnl)} />
            <Tile label="Theta / day" value={inr(data.totals.theta)} cls={tone(data.totals.theta)} />
            <Tile label="Vega / 1% IV" value={inr(data.totals.vega)} cls={tone(data.totals.vega)} />
            <Tile label="Realised" value={inr(data.totals.realised_pnl)} cls={tone(data.totals.realised_pnl)} />
          </section>

          <Alerts alerts={data.alerts} />

          {data.underlyings.length === 0 && <p className="muted">No open F&O positions.</p>}
          {data.underlyings.map((u) => (
            <UnderlyingCard key={u.underlying} u={u} />
          ))}

          <p className="muted small">Updated {new Date(data.as_of).toLocaleTimeString("en-IN")}</p>
        </>
      )}
    </main>
  );
}

function Tile({ label, value, cls }: { label: string; value: string; cls: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`value ${cls}`}>{value}</div>
    </div>
  );
}

function Alerts({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) return <p className="ok">No risk alerts.</p>;
  return (
    <ul className="alerts">
      {alerts.map((a, i) => (
        <li key={i} className={a.level}>
          <span className="badge">{a.level}</span> {a.message}
        </li>
      ))}
    </ul>
  );
}

function UnderlyingCard({ u }: { u: Underlying }) {
  const worst = Math.max(1, ...u.scenarios.map((s) => Math.abs(s.pnl)));
  return (
    <section className="card">
      <div className="card-head">
        <h2>{u.underlying}</h2>
        {u.spot && <span className="muted">Spot {num(u.spot, 2)}</span>}
        <span className={`pnl ${tone(u.pnl)}`}>{inr(u.pnl)}</span>
      </div>
      <div className="greeks">
        <span>Δ {num(u.delta)}</span>
        <span>Γ {num(u.gamma, 3)}</span>
        <span>Θ {inr(u.theta)}</span>
        <span>ν {inr(u.vega)}</span>
      </div>

      {u.scenarios.length > 0 && (
        <div className="scenarios" aria-label="P&L if spot moves">
          {u.scenarios.map((s) => (
            <div key={s.move_pct} className="scenario">
              <div className="bar-wrap">
                <div
                  className={`bar ${tone(s.pnl)}`}
                  style={{ height: `${(Math.abs(s.pnl) / worst) * 100}%` }}
                  title={inr(s.pnl)}
                />
              </div>
              <div className="small">{s.move_pct > 0 ? `+${s.move_pct}` : s.move_pct}%</div>
              <div className={`small ${tone(s.pnl)}`}>{inr(s.pnl)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Contract</th>
              <th>Lots</th>
              <th>Avg</th>
              <th>LTP</th>
              <th>P&L</th>
              <th>IV</th>
              <th>Delta</th>
              <th>Theta</th>
              <th>DTE</th>
            </tr>
          </thead>
          <tbody>
            {u.legs.map((l) => (
              <tr key={l.symbol}>
                <td>{l.symbol}</td>
                <td className={tone(l.quantity)}>{l.lots ?? l.quantity}</td>
                <td>{num(l.average_price, 2)}</td>
                <td>{num(l.ltp, 2)}</td>
                <td className={tone(l.pnl)}>{inr(l.pnl)}</td>
                <td>{l.iv ? `${num(l.iv * 100)}%` : "–"}</td>
                <td>{num(l.delta)}</td>
                <td>{inr(l.theta)}</td>
                <td>{l.days_to_expiry ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
