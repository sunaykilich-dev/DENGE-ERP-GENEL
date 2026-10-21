import { useQuery } from "@tanstack/react-query";
import { Card, Input, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api } from "../api/client";

interface DenetimKaydi {
  id: number;
  user_id: number | null;
  entity: string;
  entity_id: string | null;
  action: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  is_personal_data: boolean;
  ip: string | null;
  created_at: string;
}

function Degisim({ eski, yeni }: { eski: unknown; yeni: unknown }) {
  if (!eski && !yeni) return <Typography.Text type="secondary">—</Typography.Text>;
  const anahtarlar = new Set([
    ...Object.keys((eski as object) ?? {}),
    ...Object.keys((yeni as object) ?? {}),
  ]);
  return (
    <Space orientation="vertical" size={0}>
      {[...anahtarlar].map((k) => {
        const e = (eski as Record<string, unknown>)?.[k];
        const y = (yeni as Record<string, unknown>)?.[k];
        return (
          <span key={k} className="mono" style={{ fontSize: 12 }}>
            <strong>{k}</strong>{" "}
            {e !== undefined && (
              <Typography.Text delete type="secondary">
                {String(e)}
              </Typography.Text>
            )}
            {e !== undefined && y !== undefined && " → "}
            {y !== undefined && <Typography.Text>{String(y)}</Typography.Text>}
          </span>
        );
      })}
    </Space>
  );
}

export default function AuditPage() {
  const [entity, setEntity] = useState("");

  const kayitlar = useQuery({
    queryKey: ["denetim", entity],
    queryFn: () =>
      api.get<DenetimKaydi[]>(`/api/denetim${entity ? `?entity=${encodeURIComponent(entity)}` : ""}`),
  });

  return (
    <Card
      title="Denetim İzi"
      extra={
        <Input.Search
          placeholder="Tabloya göre filtrele (users, settings…)"
          allowClear
          onSearch={setEntity}
          style={{ width: 300 }}
        />
      }
    >
      <Typography.Paragraph type="secondary">
        Bu kayıtlar değiştirilemez; yalnızca eklenir. Kişisel veriye erişim ayrıca işaretlenir.
      </Typography.Paragraph>
      <Table
        rowKey="id"
        size="small"
        loading={kayitlar.isLoading}
        dataSource={kayitlar.data ?? []}
        columns={[
          {
            title: "Zaman",
            dataIndex: "created_at",
            width: 160,
            className: "mono",
            render: (v: string) => dayjs(v).format("DD.MM.YYYY HH:mm:ss"),
          },
          { title: "Kullanıcı", dataIndex: "user_id", width: 90, className: "mono" },
          {
            title: "Kayıt",
            width: 190,
            render: (_, k: DenetimKaydi) => (
              <span className="mono">
                {k.entity}
                {k.entity_id ? `#${k.entity_id}` : ""}
                {k.is_personal_data && (
                  <Tag color="orange" style={{ marginInlineStart: 6 }}>
                    KVKK
                  </Tag>
                )}
              </span>
            ),
          },
          { title: "Eylem", dataIndex: "action", width: 170 },
          {
            title: "Değişiklik",
            render: (_, k: DenetimKaydi) => <Degisim eski={k.old_value} yeni={k.new_value} />,
          },
          { title: "IP", dataIndex: "ip", width: 130, className: "mono" },
        ]}
      />
    </Card>
  );
}
