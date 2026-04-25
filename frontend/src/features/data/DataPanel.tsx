import { useEffect, useState } from "react";
import {
  Alert, Card, Descriptions, Space, Tag, Typography,
} from "antd";
import { DatabaseOutlined, CheckCircleOutlined, WarningOutlined } from "@ant-design/icons";
import { getCacheInfo, type CacheInfo } from "../../lib/api";

const { Text } = Typography;

interface Props {
  onDataReady: (ready: boolean) => void;
}

export function DataPanel({ onDataReady }: Props) {
  const [cacheInfo, setCacheInfo] = useState<CacheInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCacheInfo()
      .then((info) => {
        setCacheInfo(info);
        onDataReady(info.files > 10);
      })
      .catch(() => onDataReady(false))
      .finally(() => setLoading(false));
  }, [onDataReady]);

  const isReady = (cacheInfo?.files ?? 0) > 10;

  return (
    <Card
      title={
        <Space>
          <DatabaseOutlined />
          数据源
          {!loading && (isReady
            ? <Tag icon={<CheckCircleOutlined />} color="success">本地数据就绪</Tag>
            : <Tag icon={<WarningOutlined />} color="warning">数据未找到</Tag>
          )}
        </Space>
      }
      size="small"
      loading={loading}
    >
      <Space direction="vertical" style={{ width: "100%" }} size={12}>

        {cacheInfo && isReady && (
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="股票数量">
              {cacheInfo.stock_count?.toLocaleString() ?? "—"} 只
            </Descriptions.Item>
            <Descriptions.Item label="文件大小">
              {cacheInfo.size_mb} MB
            </Descriptions.Item>
            <Descriptions.Item label="数据起始">
              {cacheInfo.date_range?.start ?? "—"}
            </Descriptions.Item>
            <Descriptions.Item label="最新日期">
              <Text type="success">{cacheInfo.date_range?.end ?? "—"}</Text>
            </Descriptions.Item>
          </Descriptions>
        )}

        {cacheInfo?.error && (
          <Alert type="error" showIcon message={`读取失败: ${cacheInfo.error}`} />
        )}

        {!isReady && !loading && (
          <Alert
            type="warning"
            showIcon
            message="未找到本地行情数据"
            description={
              <>
                请确认 <Text code>DATA_DIR</Text> 环境变量指向包含{" "}
                <Text code>stock_daily.parquet</Text> 的目录。
              </>
            }
          />
        )}

      </Space>
    </Card>
  );
}
