import { useQuery } from "@tanstack/react-query";
import { Card, Drawer, Input, Space, Table, Tabs, Tag, Timeline, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import IsEmriFormu from "./IsEmriFormu";

interface Kalem {
  id: number;
  device_kimlik: string | null;
  product_name: string | null;
  action: string;
  device_role: string | null;
  payability: string;
  non_payable_reason: string | null;
  unit_price: number | null;
  price_source: string | null;
}

interface IsEmri {
  id: number;
  wo_no: string;
  type: string;
  status: string;
  customer_title: string | null;
  vehicle_plate: string | null;
  vehicle_id: number | null;
  odometer_km: number | null;
  assigned_title: string | null;
  completed_at: string | null;
  settlement_period: string;
  travel_km: number | null;
  travel_unit_price: number | null;
  blokajli: boolean;
  kalemler: Kalem[];
  toplam_tutar: number;
}

interface Donem {
  id: number;
  device_kimlik: string | null;
  vehicle_plate: string | null;
  valid_from: string;
  valid_to: string | null;
  removal_reason: string | null;
  is_inferred: boolean;
}

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const ODEME_RENGI: Record<string, string> = {
  ODENECEK: "green",
  ODENMEYECEK: "default",
  KARAR_BEKLIYOR: "gold",
};

export default function IsEmirleriPage() {
  const { yetkili } = useAuth();
  const [donem, setDonem] = useState("");
  const [sekme, setSekme] = useState("liste");
  const [secili, setSecili] = useState<IsEmri | null>(null);

  // Sayfalama SUNUCUDA; gelen liste "hepsi" değil, istenen sayfadır.
  const [sayfa, setSayfa] = useState(1);
  const SAYFA_BOYU = 20;

  const isemirleri = useQuery({
    queryKey: ["isemirleri", donem, sayfa],
    queryFn: () => {
      const p = new URLSearchParams();
      if (donem) p.set("donem", donem);
      p.set("limit", String(SAYFA_BOYU));
      p.set("offset", String((sayfa - 1) * SAYFA_BOYU));
      return api.getSayfa<IsEmri>(`/api/is-emirleri?${p}`);
    },
  });

  // Aracın geçmişindeki tüm cihazlar — kabul kriteri 3.
  const aracGecmisi = useQuery({
    queryKey: ["arac-gecmis", secili?.vehicle_id],
    queryFn: () => api.get<Donem[]>(`/api/is-emirleri/arac/${secili!.vehicle_id}/gecmis`),
    enabled: !!secili?.vehicle_id,
  });

  const liste = (
    <>
      <Typography.Paragraph type="secondary">
        Bir iş emri = <strong>bir ziyaret</strong>: araç + tarih + montaj noktası. İçindeki her
        cihaz ayrı bir kalemdir ve hak edişe kalem başına girer.
      </Typography.Paragraph>

      <Table
        rowKey="id"
        size="small"
        loading={isemirleri.isLoading}
        dataSource={isemirleri.data?.kayitlar ?? []}
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: isemirleri.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} iş emri`,
        }}
        onRow={(r) => ({ onClick: () => setSecili(r), style: { cursor: "pointer" } })}
        columns={[
          { title: "İş No", dataIndex: "wo_no", width: 130, className: "mono" },
          {
            title: "Tarih",
            dataIndex: "completed_at",
            width: 100,
            className: "mono",
            render: (v: string | null) => (v ? dayjs(v).format("DD.MM.YYYY") : "—"),
          },
          { title: "Dönem", dataIndex: "settlement_period", width: 85, className: "mono" },
          {
            title: "Tip",
            width: 130,
            render: (_, r: IsEmri) => (
              <Space size={4}>
                <Tag>{r.type.replaceAll("_", " ")}</Tag>
                {r.blokajli && (
                  <Tooltip title="Röle ile marş kesme — ürün değil montaj özelliği">
                    <Tag color="purple">blokaj</Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          { title: "Araç", dataIndex: "vehicle_plate", width: 110, className: "mono" },
          { title: "Müşteri", dataIndex: "customer_title", ellipsis: true },
          { title: "Montaj noktası", dataIndex: "assigned_title", ellipsis: true },
          {
            title: "Kalem",
            width: 70,
            className: "mono",
            render: (_, r: IsEmri) => r.kalemler.length,
          },
          {
            title: "Tutar",
            dataIndex: "toplam_tutar",
            width: 110,
            className: "tutar",
            render: tl,
          },
        ]}
      />
    </>
  );

  return (
    <Card
      title="İş Emirleri"
      extra={
        sekme === "liste" && (
          <Input.Search
            placeholder="Dönem (2026-06)"
            allowClear
            onSearch={setDonem}
            style={{ width: 200 }}
          />
        )
      }
    >
      <Tabs
        activeKey={sekme}
        onChange={setSekme}
        items={[
          { key: "liste", label: "Kayıtlar", children: liste },
          ...(yetkili("isemri.yaz")
            ? [
                {
                  key: "yeni",
                  label: "Yeni montaj / söküm",
                  children: <IsEmriFormu onKaydedildi={() => undefined} />,
                },
              ]
            : []),
        ]}
      />

      <Drawer
        title={secili ? `${secili.wo_no} · ${secili.vehicle_plate ?? "araçsız"}` : ""}
        open={!!secili}
        size={680}
        onClose={() => setSecili(null)}
      >
        {secili && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Space size={24} wrap>
              <Statistikc label="Tarih" deger={
                secili.completed_at ? dayjs(secili.completed_at).format("DD.MM.YYYY") : "—"
              } />
              <Statistikc label="Hak ediş dönemi" deger={secili.settlement_period} />
              <Statistikc label="Km" deger={secili.odometer_km?.toLocaleString("tr-TR") ?? "—"} />
              <Statistikc
                label="Yol"
                deger={
                  secili.travel_km
                    ? `${secili.travel_km} km × ${tl(secili.travel_unit_price)}`
                    : "—"
                }
              />
            </Space>

            <Card size="small" title={`Cihaz kalemleri (${secili.kalemler.length})`}>
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={secili.kalemler}
                columns={[
                  { title: "Cihaz", dataIndex: "device_kimlik", className: "mono", width: 160 },
                  { title: "Ürün", dataIndex: "product_name", ellipsis: true },
                  { title: "Eylem", dataIndex: "action", width: 110 },
                  {
                    title: "Ödenebilirlik",
                    width: 190,
                    render: (_, k: Kalem) => (
                      <Space size={4}>
                        <Tag color={ODEME_RENGI[k.payability]}>
                          {k.payability.replaceAll("_", " ")}
                        </Tag>
                        {k.non_payable_reason && (
                          <Tooltip title={k.non_payable_reason.replaceAll("_", " ")}>
                            <Tag>neden</Tag>
                          </Tooltip>
                        )}
                      </Space>
                    ),
                  },
                  {
                    title: "Tutar",
                    width: 110,
                    className: "tutar",
                    render: (_, k: Kalem) => tl(k.unit_price),
                  },
                ]}
              />
            </Card>

            {secili.vehicle_id && (
              <Card size="small" title={`${secili.vehicle_plate} aracının cihaz geçmişi`}>
                <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                  Bir araçta aynı anda birden fazla cihaz olabilir; bu liste aracın ömrü boyunca
                  takılan tüm cihazları gösterir.
                </Typography.Paragraph>
                {aracGecmisi.isLoading ? null : (aracGecmisi.data ?? []).length === 0 ? (
                  <Typography.Text type="secondary">Kayıt yok</Typography.Text>
                ) : (
                  <Timeline
                    items={(aracGecmisi.data ?? []).map((g) => ({
                      color: g.valid_to ? "gray" : "green",
                      children: (
                        <Space orientation="vertical" size={0}>
                          <span className="mono">{g.device_kimlik}</span>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {dayjs(g.valid_from).format("DD.MM.YYYY")} →{" "}
                            {g.valid_to ? dayjs(g.valid_to).format("DD.MM.YYYY") : "takılı"}
                            {g.is_inferred && (
                              <Tooltip title="Kaynakta söküm kaydı yoktu; tarih sonraki montajdan çıkarıldı">
                                <Tag color="gold" style={{ marginInlineStart: 6 }}>
                                  tarih tahmini
                                </Tag>
                              </Tooltip>
                            )}
                          </Typography.Text>
                        </Space>
                      ),
                    }))}
                  />
                )}
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </Card>
  );
}

function Statistikc({ label, deger }: { label: string; deger: string }) {
  return (
    <Space orientation="vertical" size={0}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <span className="mono">{deger}</span>
    </Space>
  );
}
