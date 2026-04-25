import { useState } from "react";
import { Table, Tag, Collapse, Space, Tooltip, Typography } from "antd";
import {
  ArrowUpOutlined, ArrowDownOutlined, MinusOutlined,
} from "@ant-design/icons";
import type { TradeRecord, StockTradeDetail, TradeStock } from "../../lib/api";

const { Text } = Typography;

// ── 股票标签（悬停显示代码）─────────────────────────────

function StockTag({ s, color, icon }: {
  s: TradeStock | StockTradeDetail;
  color: string;
  icon: React.ReactNode;
}) {
  const tip = "return_pct" in s && s.return_pct != null
    ? `${s.code} · 收益 ${s.return_pct >= 0 ? "+" : ""}${s.return_pct.toFixed(2)}%`
    : s.code;
  const label = s.name.length > 4 ? s.name.slice(0, 4) + "…" : s.name;
  return (
    <Tooltip title={tip}>
      <Tag color={color} icon={icon} style={{ margin: "2px 2px", cursor: "default" }}>
        {label}
      </Tag>
    </Tooltip>
  );
}

function StockTags({ stocks, color, icon }: {
  stocks: (TradeStock | StockTradeDetail)[];
  color: string;
  icon: React.ReactNode;
}) {
  if (stocks.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
  return (
    <Space wrap size={0}>
      {stocks.map((s) => <StockTag key={s.code} s={s} color={color} icon={icon} />)}
    </Space>
  );
}

// ── 买卖明细子表 ─────────────────────────────────────────

function DetailTable({ record }: { record: TradeRecord }) {
  const boughtRows = record.bought.map((s) => ({ ...s, action: "买入" as const }));
  const soldRows = record.sold.map((s) => ({ ...s, action: "卖出" as const }));
  const rows = [...boughtRows, ...soldRows];

  if (rows.length === 0) {
    return <Text type="secondary">本次无买卖操作（仅持仓不变）</Text>;
  }

  const fmt = (v: number | null | undefined, decimals = 2, prefix = "") =>
    v != null && v > 0
      ? <Text style={{ fontSize: 12 }}>{prefix}{v.toFixed(decimals)}</Text>
      : <Text type="secondary">—</Text>;

  const detailCols = [
    {
      title: "操作",
      dataIndex: "action",
      key: "action",
      width: 65,
      fixed: "left" as const,
      render: (v: string) =>
        v === "买入"
          ? <Tag color="success" icon={<ArrowUpOutlined />}>买入</Tag>
          : <Tag color="error" icon={<ArrowDownOutlined />}>卖出</Tag>,
    },
    {
      title: "代码",
      dataIndex: "code",
      key: "code",
      width: 80,
      render: (v: string) => <Text code style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      width: 90,
    },
    {
      title: "买入时间",
      key: "buy_datetime",
      width: 145,
      render: (_: unknown, r: typeof rows[0]) => (
        <Text style={{ fontSize: 12 }}>{r.buy_date} {r.buy_time}</Text>
      ),
    },
    {
      title: "买入价",
      dataIndex: "buy_price",
      key: "buy_price",
      width: 75,
      align: "right" as const,
      render: (v: number) => fmt(v, 3, "¥"),
    },
    {
      title: "手数",
      dataIndex: "lots",
      key: "lots",
      width: 65,
      align: "center" as const,
      render: (v: number) =>
        v > 0 ? <Text style={{ fontSize: 12 }}>{v}手</Text> : "—",
    },
    {
      title: "买入金额",
      dataIndex: "buy_amount",
      key: "buy_amount",
      width: 95,
      align: "right" as const,
      render: (v: number) =>
        v > 0 ? <Text style={{ fontSize: 12 }}>¥{v.toLocaleString()}</Text> : "—",
    },
    {
      title: "卖出时间",
      key: "sell_datetime",
      width: 145,
      render: (_: unknown, r: typeof rows[0]) =>
        r.sell_date
          ? <Text style={{ fontSize: 12 }}>{r.sell_date} {r.sell_time}</Text>
          : <Text type="secondary">持有中</Text>,
    },
    {
      title: "卖出价",
      dataIndex: "sell_price",
      key: "sell_price",
      width: 75,
      align: "right" as const,
      render: (v: number | null) => v != null ? fmt(v, 3, "¥") : <Text type="secondary">—</Text>,
    },
    {
      title: "持有天数",
      dataIndex: "hold_days",
      key: "hold_days",
      width: 80,
      align: "center" as const,
      render: (v: number | null) =>
        v != null ? <Text style={{ fontSize: 12 }}>{v} 天</Text> : "—",
    },
    {
      title: "盈亏（元）",
      dataIndex: "profit",
      key: "profit",
      width: 100,
      align: "right" as const,
      render: (v: number | null) => {
        if (v == null) return <Text type="secondary">—</Text>;
        const color = v >= 0 ? "#cf1322" : "#389e0d";
        return (
          <Text style={{ color, fontSize: 12, fontWeight: 600 }}>
            {v >= 0 ? "+" : ""}¥{v.toLocaleString()}
          </Text>
        );
      },
    },
    {
      title: "收益率",
      dataIndex: "return_pct",
      key: "return_pct",
      width: 80,
      align: "right" as const,
      render: (v: number | null) => {
        if (v == null) return <Text type="secondary">—</Text>;
        const color = v >= 0 ? "#cf1322" : "#389e0d";
        return (
          <Text style={{ color, fontSize: 13, fontWeight: 700 }}>
            {v >= 0 ? "+" : ""}{v.toFixed(2)}%
          </Text>
        );
      },
    },
  ];

  return (
    <Table
      dataSource={rows}
      columns={detailCols}
      rowKey={(r) => `${r.action}-${r.code}`}
      size="small"
      pagination={false}
      scroll={{ x: 1050 }}
    />
  );
}

// ── 主表 ─────────────────────────────────────────────────

const mainColumns = [
  {
    title: "选股日",
    dataIndex: "rebalance_date",
    key: "rebalance_date",
    width: 105,
    render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
  },
  {
    title: "执行日",
    dataIndex: "exec_date",
    key: "exec_date",
    width: 105,
    render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
  },
  {
    title: "持股",
    dataIndex: "portfolio_size",
    key: "portfolio_size",
    width: 55,
    align: "center" as const,
    render: (v: number) => <Tag>{v}</Tag>,
  },
  {
    title: "换手",
    dataIndex: "turnover_ratio",
    key: "turnover_ratio",
    width: 65,
    align: "center" as const,
    render: (v: number) => (
      <Text type={v > 0.5 ? "danger" : "secondary"} style={{ fontSize: 12 }}>
        {(v * 100).toFixed(0)}%
      </Text>
    ),
  },
  {
    title: "成本",
    dataIndex: "trade_cost_pct",
    key: "trade_cost_pct",
    width: 75,
    align: "center" as const,
    render: (v: number) => (
      <Text type="secondary" style={{ fontSize: 12 }}>{v.toFixed(4)}%</Text>
    ),
  },
  {
    title: "买入",
    dataIndex: "bought",
    key: "bought",
    render: (stocks: StockTradeDetail[]) => (
      <StockTags stocks={stocks} color="success" icon={<ArrowUpOutlined />} />
    ),
  },
  {
    title: "卖出",
    dataIndex: "sold",
    key: "sold",
    render: (stocks: StockTradeDetail[]) => (
      <StockTags stocks={stocks} color="error" icon={<ArrowDownOutlined />} />
    ),
  },
  {
    title: "持续持有",
    dataIndex: "held",
    key: "held",
    render: (stocks: TradeStock[]) => (
      <StockTags stocks={stocks} color="default" icon={<MinusOutlined />} />
    ),
  },
];

// ── 导出组件 ─────────────────────────────────────────────

interface Props {
  records: TradeRecord[];
}

export function TradeTable({ records }: Props) {
  const [activeKey, setActiveKey] = useState<string[]>([]);

  if (records.length === 0) return null;

  return (
    <Collapse
      activeKey={activeKey}
      onChange={(k) => setActiveKey(k as string[])}
      size="small"
      items={[{
        key: "trades",
        label: (
          <Space>
            <span>买卖明细</span>
            <Tag color="blue">{records.length} 次换仓</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>（点击行展开每只股票详情）</Text>
          </Space>
        ),
        children: (
          <Table
            dataSource={records}
            columns={mainColumns}
            rowKey={(r) => r.rebalance_date}
            size="small"
            pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 次换仓` }}
            scroll={{ x: 900 }}
            expandable={{
              expandedRowRender: (record) => <DetailTable record={record} />,
              rowExpandable: (record) => record.bought.length > 0 || record.sold.length > 0,
            }}
          />
        ),
      }]}
    />
  );
}
