import { useState } from "react";
import {
  Alert, Button, Card, Col, Form, InputNumber, Row, Slider,
  Space, Spin, Tag, Tooltip, Typography,
} from "antd";
import { QuestionCircleOutlined, SearchOutlined } from "@ant-design/icons";
import { getTodayHoldings, type HoldingStock, type TodaySelectParams } from "../../lib/api";
import { HoldingsTable } from "./HoldingsTable";

const { Title, Text } = Typography;

const tip = (text: string) => (
  <Tooltip title={text}>
    <QuestionCircleOutlined style={{ color: "#8c8c8c", marginLeft: 4 }} />
  </Tooltip>
);

export function TodayPage() {
  const [loading, setLoading] = useState(false);
  const [holdings, setHoldings] = useState<HoldingStock[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm();

  const handleSearch = async (values: Record<string, unknown>) => {
    setLoading(true);
    setError(null);
    try {
      const params: TodaySelectParams = {
        max_float_mktcap: values.max_float_mktcap as number,
        min_turnover_rate: values.min_turnover_rate as number,
        min_volume_ratio: values.min_volume_ratio as number,
        max_amplitude: values.max_amplitude as number,
        limitup_lookback: values.limitup_lookback as number,
        max_positions: values.max_positions as number,
      };
      const result = await getTodayHoldings(params);
      setHoldings(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "选股失败，请确认后端服务已启动");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "24px", maxWidth: 1400, margin: "0 auto" }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>

        <div>
          <Title level={3} style={{ marginBottom: 4 }}>今日选股</Title>
          <Text type="secondary">
            直接用今日实时行情数据筛选，无需历史数据缓存。
            涨停条件会从缓存中查近期数据（若无缓存则跳过该条件）。
          </Text>
        </div>

        <Row gutter={24}>
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
                  max_positions: 20,
                }}
              >
                <Form.Item label={<span>流通市值上限{tip("≤ N亿元")}</span>} name="max_float_mktcap">
                  <InputNumber style={{ width: "100%" }} min={10} max={5000} step={50} addonAfter="亿" />
                </Form.Item>
                <Form.Item label={<span>换手率下限{tip("≥ N%")}</span>} name="min_turnover_rate">
                  <InputNumber style={{ width: "100%" }} min={0.1} max={30} step={0.5} addonAfter="%" />
                </Form.Item>
                <Form.Item label={<span>量比下限{tip("今日量比 ≥ N")}</span>} name="min_volume_ratio">
                  <InputNumber style={{ width: "100%" }} min={0.1} max={10} step={0.1} />
                </Form.Item>
                <Form.Item label={<span>振幅上限{tip("今日振幅 ≤ N%")}</span>} name="max_amplitude">
                  <InputNumber style={{ width: "100%" }} min={0.5} max={20} step={0.5} addonAfter="%" />
                </Form.Item>
                <Form.Item label={<span>涨停回看{tip("近N日出现过涨停")}</span>} name="limitup_lookback">
                  <InputNumber style={{ width: "100%" }} min={5} max={60} step={5} addonAfter="日" />
                </Form.Item>
                <Form.Item label={<span>最多持仓数{tip("超出则按换手率降序截取")}</span>} name="max_positions">
                  <Slider min={5} max={100} step={5} marks={{ 5: "5", 20: "20", 50: "50" }} />
                </Form.Item>

                <Form.Item style={{ marginBottom: 0 }}>
                  <Button
                    type="primary"
                    htmlType="submit"
                    icon={<SearchOutlined />}
                    loading={loading}
                    block
                  >
                    {loading ? "筛选中..." : "今日选股"}
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
                    正在拉取今日实时行情并筛选...
                  </div>
                </div>
              </Card>
            )}

            {!loading && holdings === null && !error && (
              <Card>
                <div style={{ textAlign: "center", padding: "60px 0", color: "#8c8c8c" }}>
                  设置条件后点击「今日选股」
                </div>
              </Card>
            )}

            {!loading && holdings !== null && (
              <Card
                title={
                  <Space>
                    今日符合条件的股票
                    <Tag color={holdings.length > 0 ? "blue" : "default"}>
                      {holdings.length} 只
                    </Tag>
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
      </Space>
    </div>
  );
}
