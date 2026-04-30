import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography
} from "antd";
import ReactECharts from "echarts-for-react";
import dayjs, { Dayjs } from "dayjs";
import {
  BacktestParams,
  BacktestProgress,
  BacktestRecordSummary,
  BacktestResponse,
  DataInfo,
  OptimizationProgress,
  OptimizationRecordSummary,
  OptimizationResultItem,
  RuleResult,
  SelectedStock,
  StockWindowResponse,
  StrategyParams,
  TradeRecord,
  cancelOptimization,
  deleteBacktestRecord,
  getBacktestRecord,
  getBacktestProgress,
  getBacktestRecords,
  getDataInfo,
  getMinute,
  getMinuteDetail,
  getOptimizationProgress,
  getOptimizationRecords,
  getStockWindow,
  resumeOptimization,
  runSelection,
  startBacktest,
  startOptimization
} from "./api";
import "./style.css";

const { Title, Text } = Typography;

const defaultStrategy: StrategyParams = {
  max_float_mktcap: 80,
  min_turnover_rate: 3,
  min_volume_ratio: 1.2,
  max_volume_ratio: 1.3,
  max_amplitude: 4,
  limitup_lookback: 20,
  require_market_up: true,
  require_intraday_checks: true,
  require_index_above_ma20: true,
  min_market_tail_return_pct: 0.05,
  min_tail_return_pct: 0.2,
  min_close_vs_vwap_pct: 0.1,
  max_morning_vwap_band_pct: 1,
  tail_volume_multiplier: 1,
  max_recent_amplitude_pct: 7,
  recent_amplitude_lookback: 5,
  max_positions: 2
};

function pct(v: number) {
  if (!Number.isFinite(v)) return "-";
  return `${(v * 100).toFixed(2)}%`;
}

function annualizedFromRecord(record: BacktestRecordSummary) {
  if (Number.isFinite(record.annualized_return)) return record.annualized_return;
  const start = dayjs(record.start_date);
  const end = dayjs(record.end_date);
  const days = end.diff(start, "day");
  if (!Number.isFinite(record.total_return) || days <= 0) return Number.NaN;
  return Math.pow(1 + record.total_return, 365 / days) - 1;
}

const exitReasonLabels: Record<string, string> = {
  take_profit: "止盈",
  stop_loss: "止损",
  max_loss: "单笔最大亏损",
  market_tail_weak: "大盘尾盘走弱",
  trend_broken: "趋势走坏",
  close: "到期卖出",
  no_next_day: "无下一交易日"
};

function exitReasonText(reason: string) {
  return exitReasonLabels[reason] ?? reason;
}

function optimizationStatusText(status: OptimizationRecordSummary["status"]) {
  const labels: Record<OptimizationRecordSummary["status"], string> = {
    queued: "排队中",
    running: "运行中",
    done: "完成",
    error: "失败",
    cancelled: "已取消"
  };
  return labels[status];
}

function parseNumberList(value: unknown, fallback: number[]) {
  const parsed = String(value ?? "")
    .split(/[,，\s]+/)
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  return parsed.length ? parsed : fallback;
}

function formatParamSummary(params: Record<string, unknown>) {
  const labels: Record<string, string> = {
    max_float_mktcap: "市值",
    max_amplitude: "振幅",
    max_volume_ratio: "量比上限",
    min_market_tail_return_pct: "大盘尾盘",
    min_tail_return_pct: "个股尾盘",
    take_profit_pct: "止盈",
    stop_loss_pct: "止损",
    max_positions: "持仓"
  };
  return Object.entries(labels)
    .filter(([key]) => params[key] !== undefined)
    .map(([key, label]) => `${label}:${params[key]}`)
    .join("  ");
}

const backtestParamLabels: Array<[keyof BacktestParams, string, (value: unknown) => string]> = [
  ["start_date", "开始", String],
  ["end_date", "结束", String],
  ["initial_capital", "初始资金", (v) => Number(v).toLocaleString()],
  ["max_position_pct", "单股仓位", (v) => pct(Number(v))],
  ["max_float_mktcap", "流通市值上限", (v) => `${v} 亿`],
  ["min_turnover_rate", "换手率下限", (v) => `${v}%`],
  ["min_volume_ratio", "量比下限", String],
  ["max_volume_ratio", "量比上限", String],
  ["max_amplitude", "振幅上限", (v) => `${v}%`],
  ["limitup_lookback", "涨停回看", (v) => `${v} 日`],
  ["min_market_tail_return_pct", "大盘尾盘涨幅", (v) => `${v}%`],
  ["min_tail_return_pct", "个股尾盘涨幅", (v) => `${v}%`],
  ["min_close_vs_vwap_pct", "收盘高于均价", (v) => `${v}%`],
  ["max_morning_vwap_band_pct", "均价线震荡", (v) => `${v}%`],
  ["tail_volume_multiplier", "尾盘放量倍数", String],
  ["max_recent_amplitude_pct", "近期振幅上限", (v) => `${v}%`],
  ["recent_amplitude_lookback", "近期振幅回看", (v) => `${v} 日`],
  ["take_profit_pct", "止盈", (v) => `${v}%`],
  ["stop_loss_pct", "止损", (v) => `${v}%`],
  ["max_trade_loss_pct", "单笔最大亏损", (v) => `${v}%`],
  ["market_tail_weak_pct", "大盘尾盘走弱", (v) => `${v}%`],
  ["trend_break_ma_window", "趋势均线", (v) => `${v} 日`],
  ["trend_exit_after_days", "趋势启用日", (v) => `${v} 日`],
  ["max_hold_days", "最大持有天数", (v) => `${v} 日`],
  ["max_positions", "最大持仓数", String],
  ["enable_trend_exit", "趋势走坏卖出", (v) => (v ? "开启" : "关闭")],
  ["require_index_above_ma20", "大盘 MA20 过滤", (v) => (v ? "开启" : "关闭")],
  ["commission_rate", "手续费", (v) => `${(Number(v) * 10000).toFixed(2)} BP`]
];

function BacktestParamDetails({ params }: { params: BacktestParams }) {
  return (
    <Descriptions bordered size="small" column={4}>
      {backtestParamLabels.map(([key, label, format]) => (
        <Descriptions.Item key={key} label={label}>
          {format(params[key])}
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}

function backtestParamsToFormValues(params: BacktestParams) {
  return {
    ...params,
    start_date: dayjs(params.start_date),
    end_date: dayjs(params.end_date),
    max_position_pct: params.max_position_pct * 100,
    commission_rate: params.commission_rate * 10000
  };
}

function buildDefaultBacktestParams(startDate: string, endDate: string): BacktestParams {
  return {
    ...defaultStrategy,
    start_date: startDate,
    end_date: endDate,
    initial_capital: 100000,
    max_position_pct: 0.3,
    take_profit_pct: 5,
    stop_loss_pct: 5,
    max_trade_loss_pct: 5,
    market_tail_weak_pct: -0.3,
    trend_break_ma_window: 5,
    trend_exit_after_days: 3,
    max_hold_days: 5,
    enable_trend_exit: true,
    commission_rate: 0.001
  };
}

function stockDetailUrl(code: string, name: string, centerDate: string) {
  const params = new URLSearchParams({ code, name, date: centerDate });
  return `/stock-detail?${params.toString()}`;
}

function buildMinuteOption(title: string, bars: { dt: string; close: number; vwap: number; vol: number }[]) {
  return {
    title: { text: title, left: 8, textStyle: { fontSize: 13 } },
    tooltip: { trigger: "axis" },
    legend: { data: ["收盘", "均价线", "成交量"], top: 24 },
    grid: [
      { left: 54, right: 18, top: 58, height: 145 },
      { left: 54, right: 18, top: 225, height: 58 }
    ],
    xAxis: [
      { type: "category", data: bars.map((b) => b.dt.slice(11, 16)), boundaryGap: false },
      { type: "category", data: bars.map((b) => b.dt.slice(11, 16)), gridIndex: 1, boundaryGap: true }
    ],
    yAxis: [
      { type: "value", scale: true },
      { type: "value", gridIndex: 1, scale: true }
    ],
    dataZoom: [{ type: "inside", xAxisIndex: [0, 1] }],
    series: [
      { name: "收盘", type: "line", data: bars.map((b) => b.close), symbol: "none" },
      { name: "均价线", type: "line", data: bars.map((b) => b.vwap), symbol: "none" },
      { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: bars.map((b) => b.vol), itemStyle: { color: "#8c8c8c" } }
    ]
  };
}

function RuleTags({ rules }: { rules: RuleResult[] }) {
  return (
    <Space wrap size={[4, 4]}>
      {rules.map((r) => (
        <Tag key={r.name} color={r.passed ? "success" : "error"}>
          {r.name}: {r.passed ? "通过" : "未过"}
        </Tag>
      ))}
    </Space>
  );
}

function DataPanel() {
  const [info, setInfo] = useState<DataInfo | null>(null);
  const [error, setError] = useState("");
  const [minuteError, setMinuteError] = useState("");
  const [minuteLoading, setMinuteLoading] = useState(false);
  const [minuteTitle, setMinuteTitle] = useState("");
  const [minuteOption, setMinuteOption] = useState<object | null>(null);
  const [minuteForm] = Form.useForm();

  useEffect(() => {
    getDataInfo().then(setInfo).catch((e) => setError(e.message));
  }, []);

  async function submitMinute(values: Record<string, unknown>) {
    setMinuteError("");
    setMinuteOption(null);
    setMinuteLoading(true);
    try {
      const assetType = values.asset_type as "stock" | "index";
      const query = String(values.query || "").trim();
      const tradeDate = (values.trade_date as Dayjs).format("YYYY-MM-DD");
      const data = await getMinuteDetail(query, tradeDate, assetType);
      if (data.bars.length === 0) {
        setMinuteError("该标的在所选日期没有1分钟数据");
        return;
      }
      setMinuteTitle(`${assetType === "index" ? "大盘/指数" : "股票"} ${data.code} ${tradeDate} 1分钟图`);
      setMinuteOption(buildMinuteOption("", data.bars));
    } catch (e) {
      setMinuteError(e instanceof Error ? e.message : "分钟图加载失败");
    } finally {
      setMinuteLoading(false);
    }
  }

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={16}>
      <Card title="数据概览" size="small">
        {error && <Alert type="error" message={error} />}
        {info && (
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="数据目录">{info.data_root}</Descriptions.Item>
            <Descriptions.Item label="日线数据">{info.daily_available ? "可用" : "缺失"}</Descriptions.Item>
            <Descriptions.Item label="基础信息">{info.stock_basic_available ? "可用" : "缺失"}</Descriptions.Item>
            <Descriptions.Item label="股票数">{info.stock_count?.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="日期范围">{info.daily_start} ~ {info.daily_end}</Descriptions.Item>
            <Descriptions.Item label="股票15分钟文件">{info.stock_15min_count.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="股票1分钟文件">{info.stock_1min_count.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="指数15分钟文件">{info.index_15min_count.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="指数1分钟文件">{info.index_1min_count.toLocaleString()}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
      <Card title="分钟图查看" size="small">
        <Form
          form={minuteForm}
          layout="inline"
          initialValues={{ asset_type: "stock", query: "平安银行", trade_date: dayjs("2026-04-24") }}
          onValuesChange={(changed) => {
            if (changed.asset_type === "index") {
              minuteForm.setFieldsValue({ query: "大盘" });
            }
            if (changed.asset_type === "stock") {
              minuteForm.setFieldsValue({ query: "平安银行" });
            }
          }}
          onFinish={submitMinute}
        >
          <Form.Item label="类型" name="asset_type">
            <Select style={{ width: 120 }} options={[
              { label: "股票", value: "stock" },
              { label: "大盘/指数", value: "index" }
            ]} />
          </Form.Item>
          <Form.Item label="名称/代码" name="query">
            <Input style={{ width: 180 }} placeholder="平安银行 / 000001" />
          </Form.Item>
          <Form.Item label="日期" name="trade_date">
            <DatePicker />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={minuteLoading}>查看分钟图</Button>
          </Form.Item>
        </Form>
        {minuteError && <Alert style={{ marginTop: 12 }} type="error" message={minuteError} />}
        {minuteOption && (
          <Card size="small" title={minuteTitle} style={{ marginTop: 12 }}>
            <ReactECharts option={minuteOption} style={{ height: 430 }} />
          </Card>
        )}
      </Card>
    </Space>
  );
}

function StrategyForm({
  onFinish,
  backtest = false,
  loading = false,
  initialBacktestParams = null
}: {
  onFinish: (values: Record<string, unknown>) => void;
  backtest?: boolean;
  loading?: boolean;
  initialBacktestParams?: BacktestParams | null;
}) {
  const [form] = Form.useForm();
  const initialValues = {
    ...defaultStrategy,
    trade_date: dayjs("2026-04-24"),
    start_date: dayjs("2025-01-01"),
    end_date: dayjs("2026-04-24"),
    initial_capital: 100000,
    max_position_pct: 30,
    take_profit_pct: 5,
    stop_loss_pct: 5,
    max_trade_loss_pct: 5,
    market_tail_weak_pct: -0.3,
    trend_break_ma_window: 5,
    trend_exit_after_days: 3,
    max_hold_days: 5,
    enable_trend_exit: true,
    commission_rate: 10,
    ...(backtest && initialBacktestParams ? backtestParamsToFormValues(initialBacktestParams) : {})
  };

  useEffect(() => {
    if (backtest && initialBacktestParams) {
      form.setFieldsValue(backtestParamsToFormValues(initialBacktestParams));
    }
  }, [backtest, form, initialBacktestParams]);

  return (
    <Form
      form={form}
      layout="vertical"
      size="small"
      initialValues={initialValues}
      onFinish={onFinish}
    >
      {backtest ? (
        <Row gutter={8}>
          <Col span={12}><Form.Item label="开始" name="start_date"><DatePicker /></Form.Item></Col>
          <Col span={12}><Form.Item label="结束" name="end_date"><DatePicker /></Form.Item></Col>
        </Row>
      ) : (
        <Form.Item label="选股日期" name="trade_date"><DatePicker /></Form.Item>
      )}
      <Row gutter={8}>
        <Col span={12}><Form.Item label="市值上限(亿)" name="max_float_mktcap"><InputNumber min={1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="换手率(%)" name="min_turnover_rate"><InputNumber min={0} /></Form.Item></Col>
        <Col span={12}><Form.Item label="量比下限" name="min_volume_ratio"><InputNumber min={0} step={0.1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="量比上限" name="max_volume_ratio"><InputNumber min={0} step={0.1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="振幅(%)" name="max_amplitude"><InputNumber min={0} /></Form.Item></Col>
        <Col span={12}><Form.Item label="涨停回看" name="limitup_lookback"><InputNumber min={1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="最多股票" name="max_positions"><InputNumber min={1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="大盘尾盘涨幅(%)" name="min_market_tail_return_pct"><InputNumber min={0} step={0.05} /></Form.Item></Col>
        <Col span={12}><Form.Item label="个股尾盘涨幅(%)" name="min_tail_return_pct"><InputNumber min={0} step={0.05} /></Form.Item></Col>
        <Col span={12}><Form.Item label="收盘高于均价(%)" name="min_close_vs_vwap_pct"><InputNumber min={0} step={0.05} /></Form.Item></Col>
        <Col span={12}><Form.Item label="均价线震荡(%)" name="max_morning_vwap_band_pct"><InputNumber min={0} step={0.1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="尾盘放量倍数" name="tail_volume_multiplier"><InputNumber min={0} step={0.1} /></Form.Item></Col>
        <Col span={12}><Form.Item label="近期振幅上限(%)" name="max_recent_amplitude_pct"><InputNumber min={0} step={0.5} /></Form.Item></Col>
        <Col span={12}><Form.Item label="振幅回看日" name="recent_amplitude_lookback"><InputNumber min={2} max={20} /></Form.Item></Col>
        <Col span={12}><Form.Item label="大盘MA20过滤" name="require_index_above_ma20" valuePropName="checked"><Switch /></Form.Item></Col>
      </Row>
      {backtest && (
        <Row gutter={8}>
          <Col span={12}><Form.Item label="初始资金" name="initial_capital"><InputNumber min={10000} /></Form.Item></Col>
          <Col span={12}><Form.Item label="单股仓位(%)" name="max_position_pct"><InputNumber min={1} max={100} /></Form.Item></Col>
          <Col span={12}><Form.Item label="止盈(%)" name="take_profit_pct"><InputNumber min={0} /></Form.Item></Col>
          <Col span={12}><Form.Item label="止损(%)" name="stop_loss_pct"><InputNumber min={0} /></Form.Item></Col>
          <Col span={12}><Form.Item label="单笔最大亏损(%)" name="max_trade_loss_pct"><InputNumber min={0} /></Form.Item></Col>
          <Col span={12}><Form.Item label="大盘尾盘走弱(%)" name="market_tail_weak_pct"><InputNumber max={0} step={0.1} /></Form.Item></Col>
          <Col span={12}><Form.Item label="趋势走坏均线" name="trend_break_ma_window"><InputNumber min={2} max={20} /></Form.Item></Col>
          <Col span={12}><Form.Item label="趋势卖出启用日" name="trend_exit_after_days"><InputNumber min={1} max={20} /></Form.Item></Col>
          <Col span={12}><Form.Item label="最多持有天数" name="max_hold_days"><InputNumber min={1} max={20} /></Form.Item></Col>
          <Col span={12}><Form.Item label="趋势走坏卖出" name="enable_trend_exit" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={12}><Form.Item label="手续费(BP)" name="commission_rate"><InputNumber min={0} /></Form.Item></Col>
        </Row>
      )}
      <Button type="primary" htmlType="submit" loading={loading} disabled={loading} block>
        {backtest ? "运行回测" : "运行选股"}
      </Button>
    </Form>
  );
}

function toStrategy(values: Record<string, unknown>): StrategyParams {
  return {
    ...defaultStrategy,
    max_float_mktcap: Number(values.max_float_mktcap),
    min_turnover_rate: Number(values.min_turnover_rate),
    min_volume_ratio: Number(values.min_volume_ratio),
    max_volume_ratio: Number(values.max_volume_ratio),
    max_amplitude: Number(values.max_amplitude),
    limitup_lookback: Number(values.limitup_lookback),
    require_index_above_ma20: Boolean(values.require_index_above_ma20),
    min_market_tail_return_pct: Number(values.min_market_tail_return_pct),
    min_tail_return_pct: Number(values.min_tail_return_pct),
    min_close_vs_vwap_pct: Number(values.min_close_vs_vwap_pct),
    max_morning_vwap_band_pct: Number(values.max_morning_vwap_band_pct),
    tail_volume_multiplier: Number(values.tail_volume_multiplier),
    max_recent_amplitude_pct: Number(values.max_recent_amplitude_pct),
    recent_amplitude_lookback: Number(values.recent_amplitude_lookback),
    max_positions: Number(values.max_positions)
  };
}

function SelectionPanel() {
  const [result, setResult] = useState<Awaited<ReturnType<typeof runSelection>> | null>(null);
  const [minuteOption, setMinuteOption] = useState<object | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(values: Record<string, unknown>) {
    setError("");
    setMinuteOption(null);
    setLoading(true);
    try {
      const tradeDate = (values.trade_date as Dayjs).format("YYYY-MM-DD");
      setResult(await runSelection(tradeDate, toStrategy(values)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "选股失败");
    } finally {
      setLoading(false);
    }
  }

  async function showMinute(stock: SelectedStock) {
    const data = await getMinute(stock.code, stock.trade_date);
    setMinuteOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["收盘", "均价线"] },
      xAxis: { type: "category", data: data.bars.map((b) => b.dt.slice(11, 16)) },
      yAxis: { type: "value", scale: true },
      series: [
        { name: "收盘", type: "line", data: data.bars.map((b) => b.close) },
        { name: "均价线", type: "line", data: data.bars.map((b) => b.vwap) }
      ]
    });
  }

  return (
    <Row gutter={16}>
      <Col span={6}><Card size="small" title="文章策略参数"><StrategyForm onFinish={submit} loading={loading} /></Card></Col>
      <Col span={18}>
        <Space orientation="vertical" style={{ width: "100%" }}>
          {error && <Alert type="error" message={error} />}
          {result && (
            <Card size="small" title={`${result.trade_date} 选股结果`}>
              <Space orientation="vertical" style={{ width: "100%" }}>
                <RuleTags rules={result.market_rules} />
                <Text type="secondary">基础候选池：{result.total_candidates}，最终入选：{result.selected.length}</Text>
                <Table<SelectedStock>
                  size="small"
                  rowKey="code"
                  dataSource={result.selected}
                  expandable={{ expandedRowRender: (r) => <RuleTags rules={r.rules} /> }}
                  columns={[
                    {
                      title: "代码",
                      dataIndex: "code",
                      render: (_, r) => <a href={stockDetailUrl(r.code, r.name, r.trade_date)} target="_blank" rel="noreferrer">{r.code}</a>
                    },
                    {
                      title: "名称",
                      dataIndex: "name",
                      render: (_, r) => <a href={stockDetailUrl(r.code, r.name, r.trade_date)} target="_blank" rel="noreferrer">{r.name}</a>
                    },
                    { title: "分数", dataIndex: "score", sorter: (a, b) => a.score - b.score },
                    { title: "买价", dataIndex: "buy_price" },
                    { title: "市值", dataIndex: "float_mktcap" },
                    { title: "换手", dataIndex: "turnover_rate" },
                    { title: "量比", dataIndex: "volume_ratio" },
                    { title: "尾盘涨幅", dataIndex: "tail_return_pct" },
                    { title: "操作", render: (_, r) => <Button size="small" onClick={() => showMinute(r)}>分时</Button> }
                  ]}
                />
              </Space>
            </Card>
          )}
          {minuteOption && <Card size="small" title="尾盘分时与均价线"><ReactECharts option={minuteOption} style={{ height: 300 }} /></Card>}
        </Space>
      </Col>
    </Row>
  );
}

function BacktestPanel({ initialParams }: { initialParams: BacktestParams | null }) {
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [records, setRecords] = useState<BacktestRecordSummary[]>([]);
  const [progress, setProgress] = useState<BacktestProgress | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function refreshRecords() {
    try {
      setRecords(await getBacktestRecords());
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取回测记录失败");
    }
  }

  useEffect(() => {
    refreshRecords();
  }, []);

  async function openRecord(recordId: string) {
    setError("");
    try {
      setResult(await getBacktestRecord(recordId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载回测记录失败");
    }
  }

  async function removeRecord(recordId: string) {
    setError("");
    try {
      await deleteBacktestRecord(recordId);
      if (records[0]?.id === recordId) {
        setResult(null);
      }
      await refreshRecords();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除回测记录失败");
    }
  }

  async function submit(values: Record<string, unknown>) {
    setError("");
    setResult(null);
    setLoading(true);
    const params: BacktestParams = {
      ...toStrategy(values),
      start_date: (values.start_date as Dayjs).format("YYYY-MM-DD"),
      end_date: (values.end_date as Dayjs).format("YYYY-MM-DD"),
      initial_capital: Number(values.initial_capital),
      max_position_pct: Number(values.max_position_pct) / 100,
      take_profit_pct: Number(values.take_profit_pct),
      stop_loss_pct: Number(values.stop_loss_pct),
      max_trade_loss_pct: Number(values.max_trade_loss_pct),
      market_tail_weak_pct: Number(values.market_tail_weak_pct),
      trend_break_ma_window: Number(values.trend_break_ma_window),
      trend_exit_after_days: Number(values.trend_exit_after_days),
      max_hold_days: Number(values.max_hold_days),
      enable_trend_exit: Boolean(values.enable_trend_exit),
      commission_rate: Number(values.commission_rate) / 10000
    };

    try {
      const { job_id } = await startBacktest(params);
      setProgress({ job_id, status: "queued", percent: 0, stage: "排队中", current_date: null, result: null, error: null });

      const timer = window.setInterval(async () => {
        try {
          const p = await getBacktestProgress(job_id);
          setProgress(p);
          if (p.status === "done") {
            window.clearInterval(timer);
            setResult(p.result);
            refreshRecords();
            setLoading(false);
          }
          if (p.status === "error") {
            window.clearInterval(timer);
            setError(p.error || "回测失败");
            setLoading(false);
          }
        } catch (e) {
          window.clearInterval(timer);
          setError(e instanceof Error ? e.message : "读取回测进度失败");
          setLoading(false);
        }
      }, 700);
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动回测失败");
      setLoading(false);
    }
  }

  const navOption = useMemo(() => result ? {
    tooltip: { trigger: "axis" },
    legend: { data: ["策略", "沪深300"] },
    xAxis: { type: "category", data: result.nav_series.map((p) => p.date) },
    yAxis: { type: "value", scale: true },
    series: [
      { name: "策略", type: "line", data: result.nav_series.map((p) => p.nav), symbol: "none" },
      { name: "沪深300", type: "line", data: result.nav_series.map((p) => p.benchmark_nav), symbol: "none" }
    ]
  } : null, [result]);

  return (
    <Row gutter={16}>
      <Col span={6}><Card size="small" title="回测参数"><StrategyForm backtest onFinish={submit} loading={loading} initialBacktestParams={initialParams} /></Card></Col>
      <Col span={18}>
        <Space orientation="vertical" style={{ width: "100%" }}>
          {error && <Alert type="error" message={error} />}
          {progress && loading && (
            <Card size="small" title="回测进度">
              <Progress percent={progress.percent} status={progress.status === "error" ? "exception" : "active"} />
              <Text type="secondary">{progress.stage}{progress.current_date ? `：${progress.current_date}` : ""}</Text>
            </Card>
          )}
          <Card size="small" title="回测记录">
            <Table<BacktestRecordSummary>
              size="small"
              rowKey="id"
              dataSource={records}
              pagination={{ pageSize: 5 }}
              columns={[
                { title: "时间", dataIndex: "created_at" },
                { title: "区间", render: (_, r) => `${r.start_date} ~ ${r.end_date}` },
                { title: "总收益", render: (_, r) => pct(r.total_return) },
                { title: "年化", render: (_, r) => pct(annualizedFromRecord(r)) },
                { title: "最大回撤", render: (_, r) => pct(r.max_drawdown) },
                { title: "胜率", render: (_, r) => pct(r.win_rate) },
                { title: "交易数", dataIndex: "trade_count" },
                {
                  title: "操作",
                  render: (_, r) => (
                    <Space>
                      <Button size="small" onClick={() => openRecord(r.id)}>查看</Button>
                      <Popconfirm
                        title="删除这条回测记录？"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={() => removeRecord(r.id)}
                      >
                        <Button size="small" danger>删除</Button>
                      </Popconfirm>
                    </Space>
                  )
                }
              ]}
            />
          </Card>
          {result && (
            <>
              <Row gutter={8}>
                <Col span={4}><Card><Text>总收益</Text><Title level={4}>{pct(result.metrics.total_return)}</Title></Card></Col>
                <Col span={4}><Card><Text>年化</Text><Title level={4}>{pct(result.metrics.annualized_return)}</Title></Card></Col>
                <Col span={4}><Card><Text>最大回撤</Text><Title level={4}>{pct(result.metrics.max_drawdown)}</Title></Card></Col>
                <Col span={4}><Card><Text>胜率</Text><Title level={4}>{pct(result.metrics.win_rate)}</Title></Card></Col>
                <Col span={4}><Card><Text>交易数</Text><Title level={4}>{result.metrics.trade_count}</Title></Card></Col>
              </Row>
              <Card size="small" title="参数详情">
                <BacktestParamDetails params={result.params} />
              </Card>
              {navOption && <Card size="small" title="净值曲线"><ReactECharts option={navOption} style={{ height: 320 }} /></Card>}
              <Card size="small" title="交易明细">
                <Table<TradeRecord> size="small" rowKey={(r) => `${r.code}-${r.buy_date}-${r.buy_time}`} dataSource={result.trades} columns={[
                  { title: "买入日", dataIndex: "buy_date", sorter: (a, b) => a.buy_date.localeCompare(b.buy_date) },
                  { title: "买入时间", dataIndex: "buy_time" },
                  { title: "卖出日", dataIndex: "sell_date", sorter: (a, b) => a.sell_date.localeCompare(b.sell_date) },
                  { title: "卖出时间", dataIndex: "sell_time" },
                  {
                    title: "代码",
                    dataIndex: "code",
                    render: (_, r) => <a href={stockDetailUrl(r.code, r.name, r.buy_date)} target="_blank" rel="noreferrer">{r.code}</a>
                  },
                  {
                    title: "名称",
                    dataIndex: "name",
                    render: (_, r) => <a href={stockDetailUrl(r.code, r.name, r.buy_date)} target="_blank" rel="noreferrer">{r.name}</a>
                  },
                  { title: "买价", dataIndex: "buy_price" },
                  { title: "卖价", dataIndex: "sell_price" },
                  { title: "收益率%", dataIndex: "return_pct" },
                  { title: "利润", dataIndex: "profit" },
                  { title: "退出", dataIndex: "exit_reason", render: (reason: string) => exitReasonText(reason) }
                ]} />
              </Card>
            </>
          )}
        </Space>
      </Col>
    </Row>
  );
}

function StockDetailPage() {
  const query = new URLSearchParams(window.location.search);
  const code = query.get("code") || "";
  const name = query.get("name") || "";
  const centerDate = query.get("date") || dayjs().format("YYYY-MM-DD");
  const [data, setData] = useState<StockWindowResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getStockWindow(code, centerDate, name)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "股票分时加载失败"))
      .finally(() => setLoading(false));
  }, [code, centerDate, name]);

  return (
    <main>
      <Title level={3}>{name ? `${name} ${code}` : code}</Title>
      <Text type="secondary">中心日期：{centerDate}，展示前后各5个交易日的1分钟分时图。</Text>
      <Space orientation="vertical" style={{ width: "100%", marginTop: 16 }} size={16}>
        {loading && <Card size="small"><Progress percent={60} status="active" /></Card>}
        {error && <Alert type="error" message={error} />}
        {data?.days.map((day) => (
          <Card
            key={day.trade_date}
            size="small"
            title={`${day.trade_date}${day.trade_date === data.center_date ? " 买入日" : ""}`}
          >
            {day.bars.length ? (
              <ReactECharts option={buildMinuteOption(day.trade_date, day.bars)} style={{ height: 315 }} />
            ) : (
              <Text type="secondary">当日没有分钟数据</Text>
            )}
          </Card>
        ))}
      </Space>
    </main>
  );
}

function OptimizationPanel({ onBacktestParams }: { onBacktestParams: (params: BacktestParams) => void }) {
  const [progress, setProgress] = useState<OptimizationProgress | null>(null);
  const [records, setRecords] = useState<OptimizationRecordSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function refreshOptimizationRecords() {
    try {
      setRecords(await getOptimizationRecords());
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取参数优化记录失败");
    }
  }

  useEffect(() => {
    refreshOptimizationRecords();
  }, []);

  function watchOptimization(jobId: string) {
    setLoading(true);
    const timer = window.setInterval(async () => {
      try {
        const p = await getOptimizationProgress(jobId);
        setProgress(p);
        if (["done", "error", "cancelled"].includes(p.status)) {
          window.clearInterval(timer);
          setLoading(false);
          refreshOptimizationRecords();
          if (p.status === "error") {
            setError(p.error || "参数优化失败");
          }
        }
      } catch (e) {
        window.clearInterval(timer);
        setError(e instanceof Error ? e.message : "读取优化进度失败");
        setLoading(false);
        refreshOptimizationRecords();
      }
    }, 1000);
  }

  async function continueOptimization(recordId: string) {
    setError("");
    try {
      const { job_id } = await resumeOptimization(recordId);
      const p = await getOptimizationProgress(job_id);
      setProgress(p);
      if (!["done", "error", "cancelled"].includes(p.status)) {
        watchOptimization(job_id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "继续参数优化失败");
    }
  }

  async function viewOptimization(recordId: string) {
    setError("");
    try {
      setProgress(await getOptimizationProgress(recordId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取参数优化记录失败");
    }
  }

  async function submit(values: Record<string, unknown>) {
    setError("");
    setProgress(null);
    setLoading(true);

    const startDate = (values.start_date as Dayjs).format("YYYY-MM-DD");
    const endDate = (values.end_date as Dayjs).format("YYYY-MM-DD");
    const baseParams: BacktestParams = {
      ...buildDefaultBacktestParams(startDate, endDate),
      initial_capital: Number(values.initial_capital),
      max_position_pct: Number(values.max_position_pct) / 100,
      max_trade_loss_pct: Number(values.max_trade_loss_pct),
      market_tail_weak_pct: Number(values.market_tail_weak_pct),
      trend_break_ma_window: Number(values.trend_break_ma_window),
      trend_exit_after_days: Number(values.trend_exit_after_days),
      max_hold_days: Number(values.max_hold_days),
      commission_rate: Number(values.commission_rate) / 10000
    };

    const ranges = [
      { name: "max_float_mktcap", values: parseNumberList(values.max_float_mktcap_values, [80, 120, 200]) },
      { name: "max_amplitude", values: parseNumberList(values.max_amplitude_values, [4, 4.5, 5, 6]) },
      { name: "max_volume_ratio", values: parseNumberList(values.max_volume_ratio_values, [1.3, 1.5, 1.8, 2.0]) },
      { name: "min_market_tail_return_pct", values: parseNumberList(values.min_market_tail_return_pct_values, [0, 0.05, 0.1]) },
      { name: "min_tail_return_pct", values: parseNumberList(values.min_tail_return_pct_values, [0.1, 0.2, 0.3]) },
      { name: "take_profit_pct", values: parseNumberList(values.take_profit_pct_values, [4, 5, 6, 8]) },
      { name: "stop_loss_pct", values: parseNumberList(values.stop_loss_pct_values, [4, 5, 6]) },
      { name: "max_positions", values: parseNumberList(values.max_positions_values, [2, 3, 4]) }
    ];

    try {
      const { job_id } = await startOptimization({
        base_params: baseParams,
        ranges,
        max_workers: Number(values.max_workers),
        max_combinations: Number(values.max_combinations),
        min_trade_count: Number(values.min_trade_count),
        max_drawdown_limit: Number(values.max_drawdown_limit) / 100,
        top_n: Number(values.top_n)
      });
      setProgress({ job_id, status: "queued", percent: 0, completed: 0, total: 0, stage: "排队中", best: [], error: null });
      refreshOptimizationRecords();
      watchOptimization(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动参数优化失败");
      setLoading(false);
    }
  }

  async function cancelCurrentJob() {
    if (!progress) return;
    try {
      await cancelOptimization(progress.job_id);
      setProgress({ ...progress, stage: "取消中" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消优化任务失败");
    }
  }

  return (
    <Row gutter={16}>
      <Col span={7}>
        <Card size="small" title="参数范围">
          <Form
            layout="vertical"
            size="small"
            initialValues={{
              start_date: dayjs("2025-01-01"),
              end_date: dayjs("2026-04-24"),
              initial_capital: 100000,
              max_position_pct: 30,
              max_trade_loss_pct: 5,
              market_tail_weak_pct: -0.3,
              trend_break_ma_window: 5,
              trend_exit_after_days: 3,
              max_hold_days: 5,
              commission_rate: 10,
              max_float_mktcap_values: "80,120,200",
              max_amplitude_values: "4,4.5,5,6",
              max_volume_ratio_values: "1.3,1.5,1.8,2.0",
              min_market_tail_return_pct_values: "0,0.05,0.1",
              min_tail_return_pct_values: "0.1,0.2,0.3",
              take_profit_pct_values: "4,5,6,8",
              stop_loss_pct_values: "4,5,6",
              max_positions_values: "2,3,4",
              max_workers: 10,
              max_combinations: 6000,
              min_trade_count: 80,
              max_drawdown_limit: -20,
              top_n: 20
            }}
            onFinish={submit}
          >
            <Row gutter={8}>
              <Col span={12}><Form.Item label="开始" name="start_date"><DatePicker /></Form.Item></Col>
              <Col span={12}><Form.Item label="结束" name="end_date"><DatePicker /></Form.Item></Col>
              <Col span={12}><Form.Item label="初始资金" name="initial_capital"><InputNumber min={10000} /></Form.Item></Col>
              <Col span={12}><Form.Item label="单股仓位(%)" name="max_position_pct"><InputNumber min={1} max={100} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最大亏损(%)" name="max_trade_loss_pct"><InputNumber min={0} /></Form.Item></Col>
              <Col span={12}><Form.Item label="大盘尾盘走弱(%)" name="market_tail_weak_pct"><InputNumber max={0} step={0.1} /></Form.Item></Col>
              <Col span={12}><Form.Item label="趋势均线" name="trend_break_ma_window"><InputNumber min={2} max={20} /></Form.Item></Col>
              <Col span={12}><Form.Item label="趋势启用日" name="trend_exit_after_days"><InputNumber min={1} max={20} /></Form.Item></Col>
              <Col span={12}><Form.Item label="最大持有天数" name="max_hold_days"><InputNumber min={1} max={20} /></Form.Item></Col>
              <Col span={12}><Form.Item label="手续费(BP)" name="commission_rate"><InputNumber min={0} /></Form.Item></Col>
            </Row>
            <Form.Item label="流通市值上限(亿元)" name="max_float_mktcap_values"><Input /></Form.Item>
            <Form.Item label="日内振幅上限(%)" name="max_amplitude_values"><Input /></Form.Item>
            <Form.Item label="量比上限" name="max_volume_ratio_values"><Input /></Form.Item>
            <Form.Item label="大盘尾盘涨幅下限(%)" name="min_market_tail_return_pct_values"><Input /></Form.Item>
            <Form.Item label="个股尾盘涨幅下限(%)" name="min_tail_return_pct_values"><Input /></Form.Item>
            <Form.Item label="止盈(%)" name="take_profit_pct_values"><Input /></Form.Item>
            <Form.Item label="止损(%)" name="stop_loss_pct_values"><Input /></Form.Item>
            <Form.Item label="最大持仓数" name="max_positions_values"><Input /></Form.Item>
            <Row gutter={8}>
              <Col span={12}><Form.Item label="并行进程" name="max_workers"><InputNumber min={1} max={12} /></Form.Item></Col>
              <Col span={12}><Form.Item label="组合上限" name="max_combinations"><InputNumber min={1} max={10000} /></Form.Item></Col>
              <Col span={12}><Form.Item label="交易数目标" name="min_trade_count"><InputNumber min={0} /></Form.Item></Col>
              <Col span={12}><Form.Item label="回撤红线(%)" name="max_drawdown_limit"><InputNumber max={0} /></Form.Item></Col>
              <Col span={12}><Form.Item label="展示前N名" name="top_n"><InputNumber min={1} max={100} /></Form.Item></Col>
            </Row>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading} disabled={loading}>开始优化</Button>
              <Button onClick={cancelCurrentJob} disabled={!loading || !progress}>取消任务</Button>
            </Space>
          </Form>
        </Card>
      </Col>
      <Col span={17}>
        <Space orientation="vertical" style={{ width: "100%" }}>
          {error && <Alert type="error" message={error} />}
          <Card size="small" title="优化记录">
            <Table<OptimizationRecordSummary>
              size="small"
              rowKey="id"
              dataSource={records}
              pagination={{ pageSize: 5 }}
              columns={[
                { title: "更新时间", dataIndex: "updated_at" },
                { title: "区间", render: (_, r) => `${r.start_date} ~ ${r.end_date}` },
                { title: "状态", render: (_, r) => optimizationStatusText(r.status) },
                { title: "进度", render: (_, r) => `${r.completed}/${r.total || "-"}` },
                { title: "最佳评分", render: (_, r) => r.best_score?.toFixed(4) ?? "-" },
                { title: "最佳总收益", render: (_, r) => r.best_total_return == null ? "-" : pct(r.best_total_return) },
                { title: "最佳年化", render: (_, r) => r.best_annualized_return == null ? "-" : pct(r.best_annualized_return) },
                {
                  title: "操作",
                  render: (_, r) => (
                    <Space>
                      <Button size="small" onClick={() => viewOptimization(r.id)}>
                        查看
                      </Button>
                      <Button size="small" onClick={() => continueOptimization(r.id)} disabled={loading || r.status === "done"}>
                        继续
                      </Button>
                    </Space>
                  )
                }
              ]}
            />
          </Card>
          {progress && (
            <Card size="small" title="优化进度">
              <Progress percent={progress.percent} status={progress.status === "error" ? "exception" : progress.status === "done" ? "success" : "active"} />
              <Text type="secondary">{progress.stage} {progress.total ? `${progress.completed}/${progress.total}` : ""}</Text>
            </Card>
          )}
          <Card size="small" title="当前最优组合">
            <Table<OptimizationResultItem>
              size="small"
              rowKey={(_, index) => String(index)}
              dataSource={progress?.best || []}
              pagination={{ pageSize: 10 }}
              columns={[
                { title: "评分", dataIndex: "score", sorter: (a, b) => a.score - b.score },
                { title: "总收益", render: (_, r) => pct(r.total_return), sorter: (a, b) => a.total_return - b.total_return },
                { title: "年化", render: (_, r) => pct(r.annualized_return) },
                { title: "最大回撤", render: (_, r) => pct(r.max_drawdown), sorter: (a, b) => a.max_drawdown - b.max_drawdown },
                { title: "胜率", render: (_, r) => pct(r.win_rate) },
                { title: "交易数", dataIndex: "trade_count", sorter: (a, b) => a.trade_count - b.trade_count },
                { title: "参数", render: (_, r) => formatParamSummary(r.params) },
                {
                  title: "年度",
                  render: (_, r) => Object.entries(r.yearly_returns).map(([year, value]) => `${year}:${pct(value)}`).join("  ")
                },
                {
                  title: "操作",
                  render: (_, r) => (
                    <Button size="small" onClick={() => onBacktestParams(r.params as unknown as BacktestParams)}>
                      回测
                    </Button>
                  )
                }
              ]}
            />
          </Card>
        </Space>
      </Col>
    </Row>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState("data");
  const [backtestInitialParams, setBacktestInitialParams] = useState<BacktestParams | null>(null);

  if (window.location.pathname === "/stock-detail") {
    return <StockDetailPage />;
  }

  function openBacktestWithParams(params: BacktestParams) {
    setBacktestInitialParams(params);
    setActiveTab("backtest");
  }

  return (
    <main>
      <Title level={3}>文章版尾盘30分钟选股法</Title>
      <Text type="secondary">按原文拆成大盘过滤、日线五条件、尾盘分时确认、次日多条件卖出，并逐条展示规则。</Text>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        { key: "data", label: "数据查看", children: <DataPanel /> },
        { key: "select", label: "选股", children: <SelectionPanel /> },
        { key: "backtest", label: "回测", children: <BacktestPanel initialParams={backtestInitialParams} /> },
        { key: "optimize", label: "参数优化", children: <OptimizationPanel onBacktestParams={openBacktestWithParams} /> }
      ]} />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
