import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { BacktestPage } from "./features/backtest/BacktestPage";
import { StockMinutePage } from "./features/chart/StockMinutePage";
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
      <BrowserRouter>
        <div style={{ minHeight: "100vh", background: "#f5f7fa" }}>
          <Routes>
            <Route path="/" element={<BacktestPage />} />
            <Route path="/stock/:code/:date" element={<StockMinutePage />} />
          </Routes>
        </div>
      </BrowserRouter>
    </ConfigProvider>
  );
}
