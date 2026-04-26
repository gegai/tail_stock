import { useEffect, useState } from "react";
import {
  Alert, Button, Card, Col, DatePicker, Form, InputNumber,
  Row, Space, Spin, Tag, Tooltip, Typography,
} from "antd";
import { QuestionCircleOutlined, SearchOutlined, ApiOutlined, DatabaseOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import {
  selectStocks, getAvailableDateRange,
  type HoldingStock, type SelectParams, type DateRangeInfo,
} from "../../lib/api";
import { HoldingsTable } from "./HoldingsTable";

const { Text } = Typography;

const tip = (text: string) => (
  <Tooltip title={text}><QuestionCircleOutlined style={{ color: "#8c8c8c", marginLeft: 4 }} /></Tooltip>
);

export function TodayPage() {
  const [loading, setLoading] = useState(false);
  const [holdings, setHoldings] = useState<HoldingStock[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dateInfo, setDateInfo] = useState<DateRangeInfo | null>(null);
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [dataSource, setDataSource] = useState<"parquet" | "tushare" | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    getAvailableDateRange().then(setDateInfo).catch(() => {});
  }, []);

  const isInParquet = (d: Dayjs): boolean => {
    if (!dateInfo?.start || !dateInfo?.end) return false;
    const ds = d.format("YYYY-MM-DD");
    return ds >= dateInfo.start && ds <= dateInfo.end;
  };

  const isToday = selectedDate.isSame(dayjs(), "day");
  const inParquet = isInParquet(selectedDate);
  const needsTushare = !inParquet;
  const tushareOk = dateInfo?.tushare_configured ?? false;

  const handleSearch = async (values: Record<string, unknown>) => {
    if (needsTushare && !tushareOk) return;
    setLoading(true);
    setError(null);
    setDataSource(null);
    try {
      const params: SelectParams = {
        trade_date: selectedDate.format("YYYY-MM-DD"),
        max_float_mktcap: values.max_float_mktcap as number,
        min_turnover_rate: values.min_turnover_rate as number,
        min_volume_ratio: values.min_volume_ratio as number,
        max_amplitude: values.max_amplitude as number,
        limitup_lookback: values.limitup_lookback as number,
        max_positions: values.max_positions as number,
      };
      const result = await selectStocks(params);
      setHoldings(result);
      setDataSource(inParquet ? "parquet" : "tushare");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "选股失败";
      setError(msg.includes("response") ? "后端连接失败，请确认服务已启动" : msg);
    } finally {
      setLoading(false);
    }
  };

  const sourceTag = dataSource === "tushare"
    ? <Tag icon={<ApiOutlined />} color="processing">Tushare 实时</Tag>
    : dataSource === "parquet"
      ? <Tag icon={<DatabaseOutlined />} color="success">本地历史数据</Tag>
      : null;

  return (
    <Row gutter={24} style={{ padding: "0 8px" }}>
      {/* 条件面板 */}
      <Col xs={24} md={8} lg={6}>
        <Card title="筛选条件" size="small">
          <Form
            form={form}
            layout="vertical"
            size="small"
            onFinish={handleSearch}
            initialValues={{
              max_float_mktcap: 200,
              min_turnover_rate: 3,
              min_volume_ratio: 1.2,
              max_amplitude: 5,
              limitup_lookback: 20,
              max_positions: 5,
            }}
          >
            {/* 日期选择 */}
            <Form.Item label={<span>选股日期{tip("历史日期用本地数据；今日/未来日期调 Tushare")}</span>}>
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                <DatePicker
                  style={{ width: "100%" }}
                  value={selectedDate}
                  onChange={(d) => { if (d) { setSelectedDate(d); setHoldings(null); } }}
                  disabledDate={(d) => d.isAfter(dayjs())}
                  allowClear={false}
                />
                {isToday && !inParquet && (
                  tushareOk
                    ? <Tag icon={<ApiOutlined />} color="blue">今日→ Tushare 实时</Tag>
                    : <Tag color="warning">今日数据需配置 TUSHARE_TOKEN</Tag>
                )}
                {!isToday && inParquet && (
                  <Tag icon={<DatabaseOutlined />} color="green">历史数据（本地 parquet）</Tag>
                )}
                {dateInfo?.end && (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    本地数据最新：{dateInfo.end}
                  </Text>
                )}
              </Space>
            </Form.Item>

            <Form.Item label={<span>流通市值上限{tip("≤ N亿元")}</span>} name="max_float_mktcap">
              <InputNumber style={{ width: "100%" }} min={10} max={5000} step={50} addonAfter="亿" />
            </Form.Item>
            <Form.Item label={<span>换手率下限{tip("≥ N%")}</span>} name="min_turnover_rate">
              <InputNumber style={{ width: "100%" }} min={0.1} max={30} step={0.5} addonAfter="%" />
            </Form.Item>
            <Form.Item label={<span>量比下限{tip("当日量比 ≥ N")}</span>} name="min_volume_ratio">
              <InputNumber style={{ width: "100%" }} min={0.1} max={10} step={0.1} />
            </Form.Item>
            <Form.Item label={<span>振幅上限{tip("日内振幅 ≤ N%")}</span>} name="max_amplitude">
              <InputNumber style={{ width: "100%" }} min={0.5} max={20} step={0.5} addonAfter="%" />
            </Form.Item>
            <Form.Item label={<span>涨停回看{tip("近N日出现过涨停")}</span>} name="limitup_lookback">
              <InputNumber style={{ width: "100%" }} min={5} max={60} step={5} addonAfter="日" />
            </Form.Item>
            <Form.Item label={<span>最大持仓数{tip("超出则按换手率降序截取")}</span>} name="max_positions">
              <InputNumber style={{ width: "100%" }} min={1} max={100} step={1} addonAfter="只" />
            </Form.Item>

            {needsTushare && !tushareOk && (
              <Alert
                type="warning"
                showIcon
                message="需要 Tushare Token"
                description={<>该日期数据不在本地，请在 <Text code>.env</Text> 中配置 <Text code>TUSHARE_TOKEN=your_token</Text></>}
                style={{ marginBottom: 8 }}
              />
            )}

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                icon={<SearchOutlined />}
                loading={loading}
                block
                disabled={needsTushare && !tushareOk}
              >
                {loading ? "选股中..." : "开始选股"}
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </Col>

      {/* 结果区 */}
      <Col xs={24} md={16} lg={18}>
        {error && (
          <Alert type="error" message="选股失败" description={error} showIcon closable
            onClose={() => setError(null)} style={{ marginBottom: 16 }} />
        )}
        {loading && (
          <Card>
            <div style={{ textAlign: "center", padding: "40px 0" }}>
              <Spin size="large" />
              <div style={{ marginTop: 16, color: "#8c8c8c" }}>
                {needsTushare ? "正在调用 Tushare 获取实时行情..." : "正在从本地 parquet 筛选..."}
              </div>
            </div>
          </Card>
        )}
        {!loading && holdings === null && !error && (
          <Card>
            <div style={{ textAlign: "center", padding: "60px 0", color: "#8c8c8c" }}>
              选择日期后点击「开始选股」
            </div>
          </Card>
        )}
        {!loading && holdings !== null && (
          <Card
            title={
              <Space>
                {selectedDate.format("YYYY-MM-DD")} 选股结果
                <Tag color={holdings.length > 0 ? "blue" : "default"}>{holdings.length} 只</Tag>
                {sourceTag}
              </Space>
            }
            size="small"
          >
            {holdings.length === 0
              ? <div style={{ textAlign: "center", padding: 40, color: "#8c8c8c" }}>
                  当前条件下无符合股票，尝试放宽参数
                </div>
              : <HoldingsTable holdings={holdings} />
            }
          </Card>
        )}
      </Col>
    </Row>
  );
}
