import ReactECharts from "echarts-for-react";
import type { NavPoint } from "../../lib/api";

interface Props {
  data: NavPoint[];
}

export function NavChart({ data }: Props) {
  const dates = data.map((d) => d.date);
  const strategyNav = data.map((d) => d.strategy_nav);
  const benchmarkNav = data.map((d) => d.benchmark_nav);

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: (params: Array<{ seriesName: string; value: number; axisValue: string }>) => {
        const date = params[0]?.axisValue || "";
        return params
          .map((p) => `${p.seriesName}：<b>${p.value.toFixed(4)}</b>`)
          .join("<br/>")
          .concat(`<br/><span style="color:#8c8c8c">${date}</span>`);
      },
    },
    legend: {
      top: 8,
      data: ["微盘策略净值", "沪深300净值"],
      itemWidth: 14,
    },
    grid: { top: 48, right: 20, bottom: 40, left: 60 },
    xAxis: {
      type: "category",
      data: dates,
      axisLabel: {
        formatter: (v: string) => v.slice(0, 7),
        interval: Math.floor(dates.length / 8),
      },
      boundaryGap: false,
    },
    yAxis: {
      type: "value",
      name: "净值",
      nameTextStyle: { color: "#8c8c8c" },
      axisLabel: { formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { type: "dashed", color: "#f0f0f0" } },
    },
    series: [
      {
        name: "微盘策略净值",
        type: "line",
        data: strategyNav,
        symbol: "none",
        lineStyle: { width: 2, color: "#1677ff" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(22,119,255,0.15)" },
              { offset: 1, color: "rgba(22,119,255,0)" },
            ],
          },
        },
      },
      {
        name: "沪深300净值",
        type: "line",
        data: benchmarkNav,
        symbol: "none",
        lineStyle: { width: 1.5, color: "#8c8c8c", type: "dashed" },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 320 }}
      opts={{ renderer: "svg" }}
    />
  );
}
