import { useState } from "react";
import { Table, Tag, Collapse, Space, Typography, Select } from "antd";
import type { SelectionRecord, SelectionEntry } from "../../lib/api";

const { Text } = Typography;

interface Props {
  records: SelectionRecord[];
}

/** 将 0-100 分映射为颜色：>= 80 金色，>= 60 蓝色，其余灰色 */
function scoreColor(v: number) {
  if (v >= 80) return "#d48806";
  if (v >= 60) return "#1677ff";
  return "#595959";
}

const cols = [
  {
    title: "综合分",
    dataIndex: "score",
    key: "score",
    width: 70,
    align: "right" as const,
    render: (v: number) => (
      <Text style={{ fontSize: 12, fontWeight: 600, color: scoreColor(v ?? 0) }}>
        {(v ?? 0).toFixed(1)}
      </Text>
    ),
  },
  {
    title: "状态",
    dataIndex: "status",
    key: "status",
    width: 65,
    render: (v: string) =>
      v === "买入"
        ? <Tag color="success">买入</Tag>
        : <Tag color="default">持有</Tag>,
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
    render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
  },
  {
    title: "流通市值（亿）",
    dataIndex: "float_mktcap",
    key: "float_mktcap",
    width: 110,
    align: "right" as const,
    render: (v: number) => <Text style={{ fontSize: 12 }}>{v.toFixed(2)}</Text>,
  },
  {
    title: "换手率（%）",
    dataIndex: "turnover_rate",
    key: "turnover_rate",
    width: 100,
    align: "right" as const,
    render: (v: number) => (
      <Text style={{ fontSize: 12, color: v >= 3 ? "#cf1322" : "#595959" }}>
        {v.toFixed(3)}%
      </Text>
    ),
  },
  {
    title: "量比",
    dataIndex: "volume_ratio",
    key: "volume_ratio",
    width: 70,
    align: "right" as const,
    render: (v: number) => (
      <Text style={{ fontSize: 12, color: v >= 1.2 ? "#cf1322" : "#595959" }}>
        {v.toFixed(2)}
      </Text>
    ),
  },
  {
    title: "振幅（%）",
    dataIndex: "amplitude",
    key: "amplitude",
    width: 90,
    align: "right" as const,
    render: (v: number) => (
      <Text style={{ fontSize: 12, color: v <= 5 ? "#389e0d" : "#595959" }}>
        {v.toFixed(3)}%
      </Text>
    ),
  },
];

export function SelectionLog({ records }: Props) {
  const [selectedDate, setSelectedDate] = useState<string>(
    records.length > 0 ? records[0].date : ""
  );

  if (records.length === 0) return null;

  const current = records.find((r) => r.date === selectedDate) ?? records[0];
  const buyCount = current.stocks.filter((s) => s.status === "买入").length;
  const holdCount = current.stocks.filter((s) => s.status === "持有").length;

  const dateOptions = records.map((r) => ({
    value: r.date,
    label: `${r.date}（${r.stocks.length}只）`,
  }));

  return (
    <Collapse
      size="small"
      items={[{
        key: "log",
        label: (
          <Space>
            <span>选股日志</span>
            <Tag color="purple">{records.length} 次选股</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              每次换仓日的完整持仓 + 筛选指标
            </Text>
          </Space>
        ),
        children: (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space>
              <Text style={{ fontSize: 13 }}>选股日：</Text>
              <Select
                style={{ width: 220 }}
                value={selectedDate}
                onChange={setSelectedDate}
                options={dateOptions}
                size="small"
              />
              <Tag color="success">买入 {buyCount}</Tag>
              <Tag color="default">持有 {holdCount}</Tag>
            </Space>
            <Table
              dataSource={current.stocks}
              columns={cols}
              rowKey="code"
              size="small"
              pagination={false}
              scroll={{ x: 690 }}
            />
          </Space>
        ),
      }]}
    />
  );
}
