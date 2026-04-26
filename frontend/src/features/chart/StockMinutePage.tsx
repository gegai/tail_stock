import { useEffect, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Button, Card, Spin, Alert, Typography, Space, Tag } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import { getMinuteChart, type MinuteChartData } from "../../lib/api";

const { Title, Text } = Typography;

// ── ECharts option builder ────────────────────────────────

function buildOption(data: MinuteChartData) {
  const bars = data.bars;
  const xData = bars.map((b) => b.dt.slice(11, 16)); // HH:mm
  const kData = bars.map((b) => [b.open, b.close, b.low, b.high]);
  const volData = bars.map((b) => b.vol);

  // Day boundary indices — insert separator lines between trading days
  const dayBoundaries: number[] = [];
  let prevDay = "";
  bars.forEach((b, i) => {
    const day = b.dt.slice(0, 10);
    if (prevDay && day !== prevDay) dayBoundaries.push(i);
    prevDay = day;
  });

  // Highlight band for the trade date
  const tradeDay = data.trade_date;
  const tradeStart = bars.findIndex((b) => b.dt.startsWith(tradeDay));
  const tradeEnd = (() => {
    for (let i = bars.length - 1; i >= 0; i--) {
      if (bars[i].dt.startsWith(tradeDay)) return i;
    }
    return tradeStart;
  })();

  // Build x-axis label: show day date at first bar of each day
  const xLabels = bars.map((b, i) => {
    const day = b.dt.slice(0, 10);
    const prevDay = i > 0 ? bars[i - 1].dt.slice(0, 10) : "";
    return day !== prevDay ? day.slice(5) : b.dt.slice(11, 16);
  });

  return {
    backgroundColor: "transparent",
    animation: false,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: (params: {axisIndex: number; dataIndex: number; data: number[]; name: string}[]) => {
        const k = params.find((p) => p.axisIndex === 0);
        const v = params.find((p) => p.axisIndex === 1);
        if (!k) return "";
        const bar = bars[k.dataIndex];
        return [
          `<b>${bar.dt.slice(0, 16)}</b>`,
          `开: ${bar.open} &nbsp; 高: ${bar.high}`,
          `低: ${bar.low} &nbsp; 收: ${bar.close}`,
          v ? `量: ${(v.data as number / 10000).toFixed(2)}万` : "",
        ].filter(Boolean).join("<br/>");
      },
    },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { top: 50, right: 20, bottom: 160, left: 70 },
      { top: "72%", right: 20, bottom: 30, left: 70 },
    ],
    xAxis: [
      {
        type: "category",
        data: xLabels,
        gridIndex: 0,
        boundaryGap: false,
        axisLabel: {
          fontSize: 11,
          interval: (i: number) => dayBoundaries.includes(i) || i === 0,
          rotate: 0,
        },
        splitLine: {
          show: true,
          lineStyle: { color: "#f0f0f0" },
        },
      },
      { type: "category", data: xLabels, gridIndex: 1, show: false, boundaryGap: false },
    ],
    yAxis: [
      { type: "value", name: "价格", gridIndex: 0, scale: true, splitLine: { lineStyle: { color: "#f5f5f5" } } },
      {
        type: "value", name: "量", gridIndex: 1, scale: true,
        axisLabel: { formatter: (v: number) => `${(v / 10000).toFixed(0)}万` },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: "slider", xAxisIndex: [0, 1], bottom: 5, height: 20 },
    ],
    series: [
      {
        name: "K线",
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: kData,
        itemStyle: {
          color: "#cf1322",
          color0: "#389e0d",
          borderColor: "#cf1322",
          borderColor0: "#389e0d",
        },
        markArea: tradeStart >= 0 ? {
          silent: true,
          data: [[
            { xAxis: tradeStart, itemStyle: { color: "rgba(22,119,255,0.08)" } },
            { xAxis: tradeEnd },
          ]],
        } : undefined,
        markLine: dayBoundaries.length > 0 ? {
          silent: true,
          symbol: "none",
          data: dayBoundaries.map((i) => ({
            xAxis: i,
            lineStyle: { color: "#bfbfbf", type: "dashed", width: 1 },
          })),
          label: { show: false },
        } : undefined,
      },
      {
        name: "成交量",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volData,
        itemStyle: { color: "#8c8c8c", opacity: 0.7 },
      },
    ],
  };
}

// ── Page component ────────────────────────────────────────

export function StockMinutePage() {
  const { code, date } = useParams<{ code: string; date: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const stockName = searchParams.get("name") ?? code ?? "";

  const [data, setData] = useState<MinuteChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code || !date) return;
    setLoading(true);
    setError(null);
    getMinuteChart(code, date)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [code, date]);

  return (
    <div style={{ padding: "24px", maxWidth: 1400, margin: "0 auto" }}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>

        <Space align="center">
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/"))}
          >
            返回
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            {stockName}（{code}）
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>前后5日分时K线</Text>
          {data && (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {data.date_range.start} ~ {data.date_range.end}
              </Text>
              <Tag color="blue">执行日 {data.trade_date}</Tag>
            </>
          )}
        </Space>

        {loading && (
          <Card>
            <div style={{ textAlign: "center", padding: "80px 0" }}>
              <Spin size="large" />
              <div style={{ marginTop: 12, color: "#8c8c8c" }}>加载分时数据...</div>
            </div>
          </Card>
        )}

        {error && (
          <Alert type="error" showIcon message="加载失败" description={error} />
        )}

        {!loading && data && data.bars.length > 0 && (
          <Card size="small" title={`共 ${data.bars.length} 根分钟K线（蓝色背景为执行日）`}>
            <ReactECharts
              option={buildOption(data)}
              style={{ height: 560 }}
              opts={{ renderer: "canvas" }}
            />
          </Card>
        )}

      </Space>
    </div>
  );
}
