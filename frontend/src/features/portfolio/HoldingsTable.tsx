import { Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { HoldingStock } from "../../lib/api";

interface Props {
  holdings: HoldingStock[];
  loading?: boolean;
}

const columns: ColumnsType<HoldingStock> = [
  {
    title: "#",
    key: "index",
    width: 44,
    render: (_: unknown, __: HoldingStock, index: number) => (
      <span style={{ color: "#8c8c8c", fontSize: 12 }}>{index + 1}</span>
    ),
  },
  {
    title: "代码",
    dataIndex: "code",
    key: "code",
    width: 100,
    render: (code: string) => (
      <Tag color="blue" style={{ fontFamily: "monospace" }}>{code}</Tag>
    ),
  },
  {
    title: "名称",
    dataIndex: "name",
    key: "name",
    render: (name: string) => <Typography.Text>{name}</Typography.Text>,
  },
  {
    title: "流通市值（亿）",
    dataIndex: "market_cap",
    key: "market_cap",
    width: 130,
    sorter: (a: HoldingStock, b: HoldingStock) => a.market_cap - b.market_cap,
    render: (v: number) => (
      <span style={{ color: "#1677ff", fontWeight: 500 }}>{v.toFixed(2)}</span>
    ),
  },
  {
    title: "换手率",
    dataIndex: "turnover_rate",
    key: "turnover_rate",
    width: 90,
    sorter: (a: HoldingStock, b: HoldingStock) => a.turnover_rate - b.turnover_rate,
    defaultSortOrder: "descend",
    render: (v: number) => (
      <span style={{ color: v >= 5 ? "#cf1322" : "#262626" }}>{v.toFixed(2)}%</span>
    ),
  },
  {
    title: "权重",
    dataIndex: "weight",
    key: "weight",
    width: 80,
    render: (v: number) => `${(v * 100).toFixed(2)}%`,
  },
];

export function HoldingsTable({ holdings, loading }: Props) {
  return (
    <Table<HoldingStock>
      columns={columns}
      dataSource={holdings}
      rowKey="code"
      loading={loading}
      size="small"
      pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
      scroll={{ y: 400 }}
    />
  );
}
