import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Input, Space, Table, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";

interface Arac {
  id: number;
  plate: string;
  is_plate_verified: boolean;
  chassis_no: string | null;
  registration_no: string | null;
  brand: string | null;
  model_year: number | null;
  vehicle_type: string | null;
  customer_title: string | null;
  is_school_service: boolean;
  notes: string | null;
}

export default function AraclarPage() {
  // Genel aramadan gelen `?q=` doğrudan filtreye düşer: arama sonucuna
  // tıklayan kullanıcı filtresiz listeye değil aradığı kayda varır.
  const [aramaParam] = useSearchParams();
  const [arama, setArama] = useState(aramaParam.get("q") ?? "");
  // Sayfalama SUNUCUDA; gelen liste "hepsi" değil, istenen sayfadır.
  const [sayfa, setSayfa] = useState(1);
  const SAYFA_BOYU = 25;

  const araclar = useQuery({
    queryKey: ["araclar", arama, sayfa],
    queryFn: () => {
      const p = new URLSearchParams();
      if (arama) p.set("q", arama);
      p.set("limit", String(SAYFA_BOYU));
      p.set("offset", String((sayfa - 1) * SAYFA_BOYU));
      return api.getSayfa<Arac>(`/api/araclar?${p}`);
    },
  });

  // Uyarı TÜM veri hakkında; açık sayfadaki 25 kayıttan sayılamaz.
  const dogrulanmamisSorgu = useQuery({
    queryKey: ["araclar-dogrulanmamis"],
    queryFn: () => api.getSayfa<Arac>("/api/araclar?dogrulanmamis=true&limit=1"),
  });
  const dogrulanmamis = dogrulanmamisSorgu.data?.toplam ?? 0;

  return (
    <Card
      title="Araçlar"
      extra={
        <Input.Search
          placeholder="Plaka, şase veya ruhsat no"
          defaultValue={arama}
          allowClear
          onSearch={(v) => {
              setArama(v);
              setSayfa(1);
            }}
          style={{ width: 280 }}
        />
      }
    >
      {dogrulanmamis > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title={`${dogrulanmamis.toLocaleString("tr-TR")} araçta standart plaka yok`}
          description="Filoda iş makineleri ve demirbaş numarasıyla anılan araçlar var. Bu kayıtlar reddedilmedi; ham değer korundu ve doğrulanmadı olarak işaretlendi."
        />
      )}
      <Table
        rowKey="id"
        size="small"
        loading={araclar.isLoading}
        dataSource={araclar.data?.kayitlar ?? []}
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: araclar.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} araç`,
        }}
        columns={[
          {
            title: "Plaka",
            width: 180,
            render: (_, a: Arac) => (
              <Space size={4}>
                <span className="mono">{a.plate}</span>
                {!a.is_plate_verified && <Tag color="gold">doğrulanmadı</Tag>}
                {a.is_school_service && <Tag color="purple">okul servisi</Tag>}
              </Space>
            ),
          },
          { title: "Marka / Model", dataIndex: "brand" },
          { title: "Yıl", dataIndex: "model_year", width: 70, className: "mono" },
          { title: "Şase no", dataIndex: "chassis_no", width: 190, className: "mono" },
          { title: "Ruhsat", dataIndex: "registration_no", width: 110, className: "mono" },
          {
            title: "Müşteri",
            dataIndex: "customer_title",
            render: (v: string | null) => v ?? <Typography.Text type="secondary">—</Typography.Text>,
          },
          {
            title: "",
            width: 40,
            render: (_, a: Arac) =>
              a.notes ? (
                <Tooltip title={a.notes}>
                  <Tag>i</Tag>
                </Tooltip>
              ) : null,
          },
        ]}
      />
    </Card>
  );
}
