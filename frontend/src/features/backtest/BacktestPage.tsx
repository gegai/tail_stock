import { useState } from "react";
import { Alert, Card, Col, Row, Space, Spin, Tabs, Typography } from "antd";
import { ParamsPanel } from "./ParamsPanel";
import { StatsCards } from "./StatsCards";
import { NavChart } from "./NavChart";
import { DrawdownChart } from "./DrawdownChart";
import { TradeTable } from "./TradeTable";
import { HoldingsTable } from "../portfolio/HoldingsTable";
import { TodayPage } from "../portfolio/TodayPage";
import { DataPanel } from "../data/DataPanel";
import { runBacktest, type BacktestParams, type BacktestResult } from "../../lib/api";

const { Title, Text } = Typography;

function BacktestTab({ dataReady }: { dataReady: boolean }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async (params: BacktestParams) => {
    setLoading(true);
    setError(null);
    try {
      const res = await runBacktest(params);
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "回测请求失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Row gutter={24} align="top">
      <Col xs={24} md={7} lg={6}>
        <ParamsPanel onRun={handleRun} loading={loading} />
      </Col>
      <Col xs={24} md={17} lg={18}>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {!dataReady && (
            <Alert
              type="info"
              message="本地行情数据加载中，若回测失败请检查「数据管理」标签中的数据状态"
              showIcon
            />
          )}
          {error && (
            <Alert type="error" message="回测失败" description={error} showIcon closable
              onClose={() => setError(null)} />
          )}
          {loading && (
            <Card>
              <div style={{ textAlign: "center", padding: "40px 0" }}>
                <Spin size="large" />
                <div style={{ marginTop: 16, color: "#8c8c8c" }}>
                  回测运行中（数据已缓存，通常 10-30 秒）...
                </div>
              </div>
            </Card>
          )}
          {!loading && !result && !error && (
            <Card>
              <div style={{ textAlign: "center", padding: "60px 0", color: "#8c8c8c" }}>
                {dataReady ? "设置参数后点击「运行回测」" : "请先拉取数据"}
              </div>
            </Card>
          )}
          {!loading && result && (
            <>
              <StatsCards metrics={result.metrics} />
              <Card
                title="策略净值 vs 沪深300"
                size="small"
                extra={
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {result.params.start_date} ~ {result.params.end_date}
                  </Text>
                }
              >
                <NavChart data={result.nav_series} />
              </Card>
              <Card title="回撤曲线" size="small">
                <DrawdownChart data={result.nav_series} />
              </Card>
              <Card
                title={`当期持仓（${result.current_holdings.length} 只）`}
                size="small"
              >
                <HoldingsTable holdings={result.current_holdings} />
              </Card>
              <TradeTable records={result.trade_records} />
            </>
          )}
        </Space>
      </Col>
    </Row>
  );
}

export function BacktestPage() {
  const [dataReady, setDataReady] = useState(false);

  return (
    <div style={{ padding: "24px", maxWidth: 1600, margin: "0 auto" }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>尾盘30分钟选股法</Title>
          <Text type="secondary">
            流通市值≤200亿 · 换手率≥3% · 量比≥1.2 · 振幅≤5% · 近期有涨停 · T+1开盘执行
          </Text>
        </div>

        <Tabs
          defaultActiveKey="data"
          size="large"
          items={[
            {
              key: "data",
              label: dataReady ? "✅ 数据管理" : "① 数据管理",
              children: <DataPanel onDataReady={setDataReady} />,
            },
            {
              key: "backtest",
              label: "② 历史回测",
              children: <BacktestTab dataReady={dataReady} />,
            },
            {
              key: "today",
              label: "③ 今日选股",
              children: <TodayPage />,
            },
          ]}
        />
      </Space>
    </div>
  );
}
