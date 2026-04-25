import { Card, Col, Row, Statistic, Tooltip } from "antd";
import { ArrowUpOutlined, ArrowDownOutlined } from "@ant-design/icons";
import type { PerformanceMetrics } from "../../lib/api";

interface Props {
  metrics: PerformanceMetrics;
}

function pct(v: number, decimals = 2) {
  return `${(v * 100).toFixed(decimals)}%`;
}


export function StatsCards({ metrics }: Props) {
  const cards = [
    {
      title: "年化收益",
      value: pct(metrics.annualized_return),
      positive: metrics.annualized_return >= 0,
      tooltip: "策略年化复合收益率",
    },
    {
      title: "基准年化",
      value: pct(metrics.benchmark_annualized_return),
      positive: metrics.benchmark_annualized_return >= 0,
      tooltip: "沪深300年化收益率",
    },
    {
      title: "超额年化",
      value: pct(metrics.alpha),
      positive: metrics.alpha >= 0,
      tooltip: "策略相对沪深300的超额年化收益（Alpha）",
    },
    {
      title: "最大回撤",
      value: pct(metrics.max_drawdown),
      positive: false,
      tooltip: "回测期间最大净值回撤幅度",
    },
    {
      title: "夏普比率",
      value: metrics.sharpe_ratio.toFixed(2),
      positive: metrics.sharpe_ratio >= 1,
      tooltip: "超额收益 / 年化波动率（无风险利率 3%）",
    },
    {
      title: "卡玛比率",
      value: metrics.calmar_ratio.toFixed(2),
      positive: metrics.calmar_ratio >= 1,
      tooltip: "年化收益 / 最大回撤绝对值",
    },
    {
      title: "年化波动率",
      value: pct(metrics.annualized_volatility),
      positive: null,
      tooltip: "策略日收益率年化标准差",
    },
    {
      title: "胜率",
      value: pct(metrics.win_rate),
      positive: metrics.win_rate >= 0.5,
      tooltip: "日收益率为正的天数占比",
    },
    {
      title: "Beta",
      value: metrics.beta.toFixed(2),
      positive: null,
      tooltip: "相对沪深300的系统性风险暴露",
    },
    {
      title: "总收益",
      value: pct(metrics.total_return),
      positive: metrics.total_return >= 0,
      tooltip: "回测期间累计总收益率",
    },
  ];

  return (
    <Row gutter={[12, 12]}>
      {cards.map((c) => (
        <Col key={c.title} xs={12} sm={8} md={6} lg={4}>
          <Tooltip title={c.tooltip}>
            <Card size="small" styles={{ body: { padding: "12px 16px" } }}>
              <Statistic
                title={<span style={{ fontSize: 12, color: "#8c8c8c" }}>{c.title}</span>}
                value={c.value}
                valueStyle={{
                  fontSize: 16,
                  fontWeight: 600,
                  color:
                    c.positive === null
                      ? "#262626"
                      : c.positive
                      ? "#cf1322"
                      : "#3f8600",
                }}
                prefix={
                  c.positive === true ? (
                    <ArrowUpOutlined style={{ fontSize: 12 }} />
                  ) : c.positive === false && c.title !== "最大回撤" ? (
                    <ArrowDownOutlined style={{ fontSize: 12 }} />
                  ) : null
                }
              />
            </Card>
          </Tooltip>
        </Col>
      ))}
    </Row>
  );
}
