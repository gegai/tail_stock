import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 600_000,
});

// ── 类型定义 ──

export interface BacktestParams {
  start_date: string;
  end_date: string;
  max_float_mktcap: number;
  min_turnover_rate: number;
  min_volume_ratio: number;
  max_amplitude: number;
  limitup_lookback: number;
  max_positions: number;
  frequency: "daily" | "weekly" | "monthly";
  initial_capital: number;
  commission_rate: number;
}

export interface PerformanceMetrics {
  annualized_return: number;
  annualized_volatility: number;
  max_drawdown: number;
  sharpe_ratio: number;
  calmar_ratio: number;
  win_rate: number;
  total_return: number;
  alpha: number;
  beta: number;
  benchmark_annualized_return: number;
}

export interface NavPoint {
  date: string;
  strategy_nav: number;
  benchmark_nav: number;
  drawdown: number;
}

export interface HoldingStock {
  code: string;
  name: string;
  market_cap: number;
  turnover_rate: number;
  weight: number;
}

export interface BacktestResult {
  params: BacktestParams;
  metrics: PerformanceMetrics;
  nav_series: NavPoint[];
  current_holdings: HoldingStock[];
}

// ── API 调用 ──

export async function runBacktest(params: BacktestParams): Promise<BacktestResult> {
  const res = await api.post<BacktestResult>("/api/v1/backtest/run", params);
  return res.data;
}

export async function getCurrentHoldings(params: Partial<BacktestParams>): Promise<HoldingStock[]> {
  const res = await api.get<HoldingStock[]>("/api/v1/portfolio/current", { params });
  return res.data;
}

export async function clearBacktestCache(): Promise<void> {
  await api.delete("/api/v1/backtest/cache");
}

// ── 数据管理 ──

export interface CacheInfo {
  available: boolean;
  files: number;
  size_mb: number;
  stock_count?: number;
  date_range?: { start: string; end: string };
  error?: string;
}

export async function getCacheInfo(): Promise<CacheInfo> {
  const res = await api.get<CacheInfo>("/api/v1/data/cache-info");
  return res.data;
}

// ── 今日选股 ──

export interface TodaySelectParams {
  max_float_mktcap?: number;
  min_turnover_rate?: number;
  min_volume_ratio?: number;
  max_amplitude?: number;
  limitup_lookback?: number;
  max_positions?: number;
}

export async function getTodayHoldings(params: TodaySelectParams): Promise<HoldingStock[]> {
  const res = await api.get<HoldingStock[]>("/api/v1/portfolio/today", { params });
  return res.data;
}
