import { useQuery } from "@tanstack/react-query";
import { Card, Empty, Segmented, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AsamaEtiketi, type BagliIs } from "./SatisIsleri";

/**
 * Satışlarımın durumu (KARARLAR 2026-11-09 S4.2): kabul edilen teklifler ve
 * siparişler, bağlı kurulum/teslimat/keşif işleri ve aşamaları. Maliyet ve
 * fiyat gösterilmez. Satış müdürü (`teklif.ekip_ozet`) ekibin tümünü görür.
 */

interface Satir {
  kaynak: "TEKLIF" | "SIPARIS";
  id: number;
  no: string;
  musteri: string | null;
  satisci: string | null;
  durum: string;
  tarih: string | null;
  genel_asama: string;
  genel_asama_adi: string;
  isler: BagliIs[];
}

const GENEL_RENK: Record<string, string> = {
  IS_YOK: "default",
  DEVAM: "blue",
  ASKIDA: "orange",
  TAMAMLANDI: "green",
};

export default function SatislarimPage() {
  const { yetkili } = useAuth();
  const navigate = useNavigate();
  const [gorunum, setGorunum] = useState<"kendi" | "ekip">("kendi");
  const veri = useQuery({
    queryKey: ["satislarim", gorunum],
    queryFn: () =>
      api.get<Satir[]>(`/api/satis-takip/satislarim${gorunum === "ekip" ? "?ekip=true" : ""}`),
  });

  return (
    <Card
      title="Satışlarımın durumu"
      extra={
        yetkili("teklif.ekip_ozet") && (
          <Segmented
            value={gorunum}
            onChange={(x) => setGorunum(x as "kendi" | "ekip")}
            options={[
              { value: "kendi", label: "Benim" },
              { value: "ekip", label: "Ekip" },
            ]}
          />
        )
      }
    >
      <Typography.Paragraph type="secondary">
        Kabul edilen teklifler ve siparişler, bağlı servis işlerinin aşamasıyla. Planlamayı birim
        şefi yapar; askıdaki işin nedeni yanında yazar.
      </Typography.Paragraph>
      <Table<Satir>
        rowKey={(r) => `${r.kaynak}-${r.id}`}
        size="small"
        loading={veri.isLoading}
        dataSource={veri.data ?? []}
        locale={{ emptyText: <Empty description="Kabul edilmiş satış yok" /> }}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: true }}
        columns={[
          {
            title: "Belge",
            width: 170,
            render: (_: unknown, r: Satir) => (
              <Typography.Link
                className="mono"
                onClick={() => navigate(r.kaynak === "SIPARIS" ? "/siparisler" : "/teklifler?benim=1")}
              >
                {r.kaynak === "SIPARIS" ? "Sipariş" : "Teklif"} {r.no}
              </Typography.Link>
            ),
          },
          { title: "Müşteri", dataIndex: "musteri" },
          ...(gorunum === "ekip" ? [{ title: "Satışçı", dataIndex: "satisci" }] : []),
          {
            title: "Tarih",
            dataIndex: "tarih",
            width: 110,
            className: "mono",
            render: (x: string | null) => (x ? dayjs(x).format("DD.MM.YYYY") : "—"),
          },
          {
            title: "Genel durum",
            width: 130,
            render: (_: unknown, r: Satir) => (
              <Tag color={GENEL_RENK[r.genel_asama]}>{r.genel_asama_adi}</Tag>
            ),
          },
          {
            title: "Servis işleri",
            render: (_: unknown, r: Satir) =>
              r.isler.length === 0 ? (
                "—"
              ) : (
                <Space orientation="vertical" size={2}>
                  {r.isler.map((i) => (
                    <Space key={i.service_order_id} size={6} wrap>
                      <span className="mono">{i.so_no}</span>
                      <span>{i.bag_adi}</span>
                      <AsamaEtiketi is={i} />
                    </Space>
                  ))}
                </Space>
              ),
          },
        ]}
      />
    </Card>
  );
}
