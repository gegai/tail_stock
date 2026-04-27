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
  RuleResult,
  SelectedStock,
  StockWindowResponse,
  StrategyParams,
  deleteBacktestRecord,
  getBacktestRecord,
  getBacktestProgress,
  getBacktestRecords,
  getDataInfo,
  getMinute,
  getMinuteDetail,
  getStockWindow,
  runSelection,
  startBacktest
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
  min_market_tail_return_pct: 0.15,
  min_tail_return_pct: 0.3,
  min_close_vs_vwap_pct: 0.1,
  max_morning_vwap_band_pct: 1,
  tail_volume_multiplier: 1,
  max_recent_amplitude_pct: 7,
  recent_amplitude_lookback: 5,
  max_positions: 2
};

function pct(v: number) {
  return `${(v * 100).toFixed(2)}%`;
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
  loading = false
}: {
  onFinish: (values: Record<string, unknown>) => void;
  backtest?: boolean;
  loading?: boolean;
}) {
  return (
    <Form
      layout="vertical"
      size="small"
      initialValues={{
        ...defaultStrategy,
        trade_date: dayjs("2026-04-24"),
        start_date: dayjs("2026-04-01"),
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
        commission_rate: 15
      }}
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

function BacktestPanel() {
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
      <Col span={6}><Card size="small" title="回测参数"><StrategyForm backtest onFinish={submit} loading={loading} /></Card></Col>
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
                <Col span={6}><Card><Text>总收益</Text><Title level={4}>{pct(result.metrics.total_return)}</Title></Card></Col>
                <Col span={6}><Card><Text>最大回撤</Text><Title level={4}>{pct(result.metrics.max_drawdown)}</Title></Card></Col>
                <Col span={6}><Card><Text>胜率</Text><Title level={4}>{pct(result.metrics.win_rate)}</Title></Card></Col>
                <Col span={6}><Card><Text>交易数</Text><Title level={4}>{result.metrics.trade_count}</Title></Card></Col>
              </Row>
              {navOption && <Card size="small" title="净值曲线"><ReactECharts option={navOption} style={{ height: 320 }} /></Card>}
              <Card size="small" title="交易明细">
                <Table size="small" rowKey={(r) => `${r.code}-${r.buy_date}-${r.buy_time}`} dataSource={result.trades} columns={[
                  { title: "买入日", dataIndex: "buy_date" },
                  { title: "买入时间", dataIndex: "buy_time" },
                  { title: "卖出日", dataIndex: "sell_date" },
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
                  { title: "退出", dataIndex: "exit_reason" }
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

function App() {
  if (window.location.pathname === "/stock-detail") {
    return <StockDetailPage />;
  }

  return (
    <main>
      <Title level={3}>文章版尾盘30分钟选股法</Title>
      <Text type="secondary">按原文拆成大盘过滤、日线五条件、尾盘分时确认、次日多条件卖出，并逐条展示规则。</Text>
      <Tabs items={[
        { key: "data", label: "数据查看", children: <DataPanel /> },
        { key: "select", label: "选股", children: <SelectionPanel /> },
        { key: "backtest", label: "回测", children: <BacktestPanel /> }
      ]} />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
