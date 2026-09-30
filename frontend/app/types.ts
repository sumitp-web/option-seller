export type Leg = {
  symbol: string;
  exchange: string;
  underlying: string;
  type: "CE" | "PE" | "FUT";
  strike: number | null;
  expiry: string | null;
  quantity: number;
  lots: number | null;
  average_price: number;
  ltp: number;
  pnl: number;
  iv: number | null;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  days_to_expiry: number | null;
};

export type Underlying = {
  underlying: string;
  spot: number | null;
  pnl: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  scenarios: { move_pct: number; pnl: number }[];
  legs: Leg[];
};

export type Alert = {
  level: "critical" | "warning" | "info";
  rule: string;
  message: string;
  underlying: string | null;
  symbol: string | null;
};

export type Portfolio = {
  as_of: string;
  totals: { pnl: number; open_pnl: number; realised_pnl: number; theta: number; vega: number };
  underlyings: Underlying[];
  alerts: Alert[];
  non_fno_positions: number;
};
