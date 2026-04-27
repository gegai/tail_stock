import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8001",
  timeout: 600_000
});

export interface RuleResult {
  name: string;
  passed: boolean;
  actual: number | string | null;
  threshold: string | null;
  note: string;
}

export interface StrategyParams {
  max_float_mktcap: number;
  min_turnover_rate: number;
  min_volume_ratio: number;
  max_volume_ratio: number;
  max_amplitude: number;
  limitup_lookback: number;
  require_market_up: boolean;
  require_intraday_checks: boolean;
  require_index_above_ma20: boolean;
  min_market_tail_return_pct: number;
  min_tail_return_pct: number;
  min_close_vs_vwap_pct: number;
  max_morning_vwap_band_pct: number;
  tail_volume_multiplier: number;
  max_recent_amplitude_pct: number;
  recent_amplitude_lookback: number;
  max_positions: number;
}

export interface BacktestParams extends StrategyParams {
  start_date: string;
  end_date: string;
  initial_capital: number;
  max_position_pct: number;
  take_profit_pct: number;
  stop_loss_pct: number;
  max_trade_loss_pct: number;
  market_tail_weak_pct: number;
  trend_break_ma_window: number;
  trend_exit_after_days: number;
  max_hold_days: number;
  enable_trend_exit: boolean;
  commission_rate: number;
}

export interface SelectedStock {
  code: string;
  name: string;
  trade_date: string;
  score: number;
  buy_price: number | null;
  rules: RuleResult[];
  float_mktcap: number | null;
  turnover_rate: number | null;
  volume_ratio: number | null;
  amplitude: number | null;
  tail_return_pct: number | null;
  close_vs_vwap_pct: number | null;
  tail_volume_ratio: number | null;
}

export interface SelectionResponse {
  trade_date: string;
  benchmark_code: string;
  market_rules: RuleResult[];
  total_candidates: number;
  selected: SelectedStock[];
}

export interface DataInfo {
  data_root: string;
  daily_available: boolean;
  stock_basic_available: boolean;
  stock_15min_count: number;
  stock_1min_count: number;
  index_15min_count: number;
  index_1min_count: number;
  daily_start: string | null;
  daily_end: string | null;
  stock_count: number | null;
}

export interface TradeRecord {
  code: string;
  name: string;
  buy_date: string;
  buy_time: string;
  sell_date: string;
  sell_time: string;
  buy_price: number;
  sell_price: number;
  shares: number;
  buy_amount: number;
  sell_amount: number;
  return_pct: number;
  profit: number;
  exit_reason: string;
}

export interface NavPoint {
  date: string;
  nav: number;
  benchmark_nav: number;
  drawdown: number;
}

export interface BacktestResponse {
  metrics: {
    total_return: number;
    annualized_return: number;
    max_drawdown: number;
    win_rate: number;
    trade_count: number;
    benchmark_total_return: number;
  };
  nav_series: NavPoint[];
  trades: TradeRecord[];
  selections: SelectionResponse[];
}

export interface BacktestRecordSummary {
  id: string;
  created_at: string;
  start_date: string;
  end_date: string;
  total_return: number;
  max_drawdown: number;
  win_rate: number;
  trade_count: number;
}

export interface BacktestProgress {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  percent: number;
  stage: string;
  current_date: string | null;
  result: BacktestResponse | null;
  error: string | null;
}

export interface MinuteBar {
  dt: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  vwap: number;
}

export interface StockWindowDay {
  trade_date: string;
  bars: MinuteBar[];
}

export interface StockWindowResponse {
  code: string;
  name: string | null;
  center_date: string;
  days: StockWindowDay[];
}

export async function getDataInfo() {
  return (await api.get<DataInfo>("/api/data/info")).data;
}

export async function runSelection(tradeDate: string, params: StrategyParams) {
  return (await api.post<SelectionResponse>(`/api/select/run?trade_date=${tradeDate}`, params)).data;
}

export async function runBacktest(params: BacktestParams) {
  return (await api.post<BacktestResponse>("/api/backtest/run", params)).data;
}

export async function startBacktest(params: BacktestParams) {
  return (await api.post<{ job_id: string }>("/api/backtest/start", params)).data;
}

export async function getBacktestProgress(jobId: string) {
  return (await api.get<BacktestProgress>(`/api/backtest/progress/${jobId}`)).data;
}

export async function getBacktestRecords() {
  return (await api.get<BacktestRecordSummary[]>("/api/backtest/records")).data;
}

export async function getBacktestRecord(recordId: string) {
  return (await api.get<BacktestResponse>(`/api/backtest/records/${recordId}`)).data;
}

export async function deleteBacktestRecord(recordId: string) {
  return (await api.delete<{ ok: boolean }>(`/api/backtest/records/${recordId}`)).data;
}

export async function getMinute(code: string, tradeDate: string) {
  return (await api.get<{ code: string; trade_date: string; bars: MinuteBar[] }>(`/api/stocks/${code}/minute`, {
    params: { trade_date: tradeDate }
  })).data;
}

export async function getMinuteDetail(query: string, tradeDate: string, assetType: "stock" | "index") {
  return (await api.get<{ code: string; trade_date: string; bars: MinuteBar[] }>("/api/minute/detail", {
    params: { query, trade_date: tradeDate, asset_type: assetType }
  })).data;
}

export async function getStockWindow(code: string, centerDate: string, name?: string) {
  return (await api.get<StockWindowResponse>(`/api/stocks/${code}/window`, {
    params: { center_date: centerDate, radius: 5, freq: "1min", name }
  })).data;
}
