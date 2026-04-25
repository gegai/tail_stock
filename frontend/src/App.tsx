import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BacktestPage } from "./features/backtest/BacktestPage";
import "./index.css";

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#1677ff",
          borderRadius: 6,
        },
      }}
    >
      <div style={{ minHeight: "100vh", background: "#f5f7fa" }}>
        <BacktestPage />
      </div>
    </ConfigProvider>
  );
}
