import ReactECharts from "echarts-for-react";
import type { NavPoint } from "../../lib/api";

interface Props {
  data: NavPoint[];
}

export function DrawdownChart({ data }: Props) {
  const dates = data.map((d) => d.date);
  const drawdown = data.map((d) => +(d.drawdown * 100).toFixed(2));

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      formatter: (params: Array<{ value: number; axisValue: string }>) => {
        const p = params[0];
        return `${p.axisValue}<br/>回撤：<b style="color:#cf1322">${p.value.toFixed(2)}%</b>`;
      },
    },
    grid: { top: 32, right: 20, bottom: 40, left: 60 },
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
      name: "回撤 %",
      nameTextStyle: { color: "#8c8c8c" },
      axisLabel: { formatter: (v: number) => `${v.toFixed(0)}%` },
      splitLine: { lineStyle: { type: "dashed", color: "#f0f0f0" } },
    },
    series: [
      {
        name: "策略回撤",
        type: "line",
        data: drawdown,
        symbol: "none",
        lineStyle: { width: 0 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(207,19,34,0.6)" },
              { offset: 1, color: "rgba(207,19,34,0.05)" },
            ],
          },
        },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 200 }}
      opts={{ renderer: "svg" }}
    />
  );
}
