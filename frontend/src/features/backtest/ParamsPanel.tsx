import { Button, Card, DatePicker, Form, InputNumber, Select, Tooltip, Divider } from "antd";
import { QuestionCircleOutlined, ThunderboltOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import type { BacktestParams } from "../../lib/api";

interface Props {
  onRun: (params: BacktestParams) => void;
  loading: boolean;
}

const tip = (text: string) => (
  <Tooltip title={text}>
    <QuestionCircleOutlined style={{ color: "#8c8c8c", marginLeft: 4 }} />
  </Tooltip>
);

export function ParamsPanel({ onRun, loading }: Props) {
  const [form] = Form.useForm();

  const handleFinish = (values: Record<string, unknown>) => {
    const params: BacktestParams = {
      start_date: (values.start_date as Dayjs).format("YYYY-MM-DD"),
      end_date: (values.end_date as Dayjs).format("YYYY-MM-DD"),
      max_float_mktcap: values.max_float_mktcap as number,
      min_turnover_rate: values.min_turnover_rate as number,
      min_volume_ratio: values.min_volume_ratio as number,
      max_amplitude: values.max_amplitude as number,
      limitup_lookback: values.limitup_lookback as number,
      max_positions: values.max_positions as number,
      frequency: values.frequency as BacktestParams["frequency"],
      buy_timing: values.buy_timing as BacktestParams["buy_timing"],
      initial_capital: values.initial_capital as number,
      commission_rate: (values.commission_rate as number) / 10000,
    };
    onRun(params);
  };

  return (
    <Card
      title="策略参数"
      size="small"
      style={{ height: "100%" }}
      styles={{ body: { padding: "14px 18px" } }}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        size="small"
        initialValues={{
          start_date: dayjs("2020-01-01"),
          end_date: dayjs("2026-04-24"),
          max_float_mktcap: 200,
          min_turnover_rate: 3,
          min_volume_ratio: 1.2,
          max_amplitude: 5,
          limitup_lookback: 20,
          max_positions: 1,
          frequency: "daily",
          buy_timing: "t1_open",
          initial_capital: 100_000,
          commission_rate: 5,
        }}
      >
        {/* 时间区间 */}
        <Form.Item label="起始日期" name="start_date" rules={[{ required: true }]}>
          <DatePicker style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item label="结束日期" name="end_date" rules={[{ required: true }]}>
          <DatePicker style={{ width: "100%" }} />
        </Form.Item>

        <Divider style={{ margin: "10px 0", fontSize: 12, color: "#8c8c8c" }}>
          文章5个选股条件
        </Divider>

        {/* 条件1：流通市值 */}
        <Form.Item
          label={<span>流通市值上限（亿）{tip("≤ 该值才入选，文章默认200亿")}</span>}
          name="max_float_mktcap"
        >
          <InputNumber style={{ width: "100%" }} min={10} max={5000} step={50} addonAfter="亿" />
        </Form.Item>

        {/* 条件2：换手率 */}
        <Form.Item
          label={<span>换手率下限（%）{tip("≥ 该值才入选，文章默认3%")}</span>}
          name="min_turnover_rate"
        >
          <InputNumber style={{ width: "100%" }} min={0.1} max={30} step={0.5} addonAfter="%" />
        </Form.Item>

        {/* 条件3：量比 */}
        <Form.Item
          label={<span>量比下限{tip("当日成交量 / 近5日均量 ≥ 该值，文章默认1.2")}</span>}
          name="min_volume_ratio"
        >
          <InputNumber style={{ width: "100%" }} min={0.1} max={10} step={0.1} />
        </Form.Item>

        {/* 条件4：振幅 */}
        <Form.Item
          label={<span>振幅上限（%）{tip("(最高-最低)/昨收 ≤ 该值，文章默认5%")}</span>}
          name="max_amplitude"
        >
          <InputNumber style={{ width: "100%" }} min={0.5} max={20} step={0.5} addonAfter="%" />
        </Form.Item>

        {/* 条件5：涨停回看 */}
        <Form.Item
          label={<span>涨停回看天数{tip("过去N个交易日内出现过涨停才入选，文章未明确，默认20")}</span>}
          name="limitup_lookback"
        >
          <InputNumber style={{ width: "100%" }} min={5} max={60} step={5} addonAfter="日" />
        </Form.Item>

        <Divider style={{ margin: "10px 0", fontSize: 12, color: "#8c8c8c" }}>
          执行参数
        </Divider>

        {/* 最大持仓 */}
        <Form.Item
          label={<span>最大持仓数量{tip("满足条件的股票超过此数时，按换手率降序截取")}</span>}
          name="max_positions"
        >
          <InputNumber style={{ width: "100%" }} min={1} max={100} step={1} addonAfter="只" />
        </Form.Item>

        {/* 换仓频率 */}
        <Form.Item label="换仓频率" name="frequency">
          <Select options={[
            { label: "每日换仓（隔日卖出）", value: "daily" },
            { label: "每周换仓", value: "weekly" },
            { label: "每月换仓", value: "monthly" },
          ]} />
        </Form.Item>

        {/* 买入时机 */}
        <Form.Item
          label={<span>买入时机{tip("t_close：T日收盘价入场（近似14:30尾盘）；t1_open：T+1日09:30开盘价买入")}</span>}
          name="buy_timing"
        >
          <Select options={[
            { label: "T+1日开盘 09:30", value: "t1_open" },
            { label: "T日尾盘 14:30（收盘价）", value: "t_close" },
          ]} />
        </Form.Item>

        {/* 初始资金 */}
        <Form.Item label="初始资金（元）" name="initial_capital">
          <InputNumber
            style={{ width: "100%" }}
            min={10_000}
            step={100_000}
            formatter={(v) => `¥ ${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
            // @ts-expect-error antd parser type overly narrow
            parser={(v) => Number(v!.replace(/¥\s?|(,*)/g, ""))}
          />
        </Form.Item>

        {/* 手续费 */}
        <Form.Item
          label={<span>单边手续费{tip("1BP=0.01%。买入5BP+卖出含印花税10BP，建议15BP")}</span>}
          name="commission_rate"
        >
          <InputNumber style={{ width: "100%" }} min={0} max={100} addonAfter="BP" />
        </Form.Item>

        <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
          <Button
            type="primary"
            htmlType="submit"
            icon={<ThunderboltOutlined />}
            loading={loading}
            block
            size="middle"
          >
            {loading ? "回测运行中..." : "运行回测"}
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
}
