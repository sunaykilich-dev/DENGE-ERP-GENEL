import { useQuery } from "@tanstack/react-query";
import { Card, Col, DatePicker, Empty, Row, Segmented, Select, Space, Table, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Statistic from "../components/Statistic";

/**
 * Tekliflerim (KARARLAR 2026-11-09 S2.2): satışçının kendi teklifleri — açık,
 * kazanılan, kaybedilen, süresi dolan, oranlar ve kaybedilenlerde nedene göre
 * dağılım. Dönem teklifin açılış tarihine göredir. Satış müdürü
 * (`teklif.ekip_ozet`) aynı görünümü satışçı kırılımıyla görür.
 */

interface Metrik {
  toplam: number;
  acik: number;
  kazanilan: number;
  kaybedilen: number;
  suresi_dolan: number;
  iptal: number;
  kazanma_orani: number | null;
  kayip_orani: number | null;
  sure_dolma_orani: number | null;
}

interface Ozet {
  tarih_bas: string;
  tarih_bit: string;
  ozet: Metrik;
  kayip_nedenleri: { kod: string; neden: string; adet: number }[];
  satiscilar: (Metrik & { owner_id: number | null; ad: string })[];
}

const oran = (x: number | null) => (x == null ? "—" : `%${x.toLocaleString("tr-TR")}`);

export default function TekliflerimPage() {
  const { yetkili } = useAuth();
  const navigate = useNavigate();
  const ekipYetkisi = yetkili("teklif.ekip_ozet");
  const [aralik, setAralik] = useState<[Dayjs, Dayjs]>([dayjs().subtract(90, "day"), dayjs()]);
  const [tur, setTur] = useState<"SATIS" | "SERVIS" | undefined>();
  const [gorunum, setGorunum] = useState<"kendi" | "ekip">("kendi");

  const p = new URLSearchParams({
    tarih_bas: aralik[0].format("YYYY-MM-DD"),
    tarih_bit: aralik[1].format("YYYY-MM-DD"),
  });
  if (tur) p.set("tur", tur);
  if (gorunum === "ekip") p.set("ekip", "true");

  const veri = useQuery({
    queryKey: ["tekliflerim", p.toString()],
    queryFn: () => api.get<Ozet>(`/api/satis-takip/tekliflerim?${p}`),
  });
  const o = veri.data?.ozet;

  const kutular: { baslik: string; deger: number | string | undefined; yol?: string }[] = [
    { baslik: "Açık", deger: o?.acik, yol: "/teklifler?benim=1&kpi=musteri_yaniti_bekleyen" },
    { baslik: "Kazanılan", deger: o?.kazanilan },
    { baslik: "Kaybedilen", deger: o?.kaybedilen },
    { baslik: "Süresi dolan", deger: o?.suresi_dolan, yol: "/teklifler?benim=1&kpi=suresi_dolan" },
    { baslik: "Kazanma oranı", deger: o ? oran(o.kazanma_orani) : undefined },
    { baslik: "Kayıp oranı", deger: o ? oran(o.kayip_orani) : undefined },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title={gorunum === "ekip" ? "Teklif sonuçları — satışçı kırılımı" : "Tekliflerim"}
        extra={
          <Space wrap>
            {ekipYetkisi && (
              <Segmented
                value={gorunum}
                onChange={(x) => setGorunum(x as "kendi" | "ekip")}
                options={[
                  { value: "kendi", label: "Benim" },
                  { value: "ekip", label: "Ekip" },
                ]}
              />
            )}
            <Select
              allowClear
              placeholder="Tür"
              style={{ width: 120 }}
              value={tur}
              onChange={setTur}
              options={[
                { value: "SATIS", label: "Satış" },
                { value: "SERVIS", label: "Servis" },
              ]}
            />
            <DatePicker.RangePicker
              format="DD.MM.YYYY"
              value={aralik}
              allowClear={false}
              onChange={(x) => x && x[0] && x[1] && setAralik([x[0], x[1]])}
            />
          </Space>
        }
      >
        <Row gutter={[12, 12]}>
          {kutular.map((k) => (
            <Col key={k.baslik} xs={12} sm={8} lg={4}>
              <Card
                size="small"
                hoverable={!!k.yol && gorunum === "kendi"}
                onClick={() => k.yol && gorunum === "kendi" && navigate(k.yol)}
                style={{ height: "100%" }}
              >
                <Statistic title={k.baslik} value={k.deger ?? "—"} />
              </Card>
            </Col>
          ))}
        </Row>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          Oranlar sonuçlanan tekliflere göredir (kazanılan + kaybedilen + süresi dolan); açık teklif
          paydaya girmez. Toplam {o?.toplam ?? 0} teklif, iptal {o?.iptal ?? 0}.
        </Typography.Paragraph>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={gorunum === "ekip" ? 8 : 12}>
          <Card title="Kaybedilme nedenleri" size="small">
            {(veri.data?.kayip_nedenleri ?? []).length === 0 ? (
              <Empty description="Kaybedilen teklif yok" />
            ) : (
              <Table
                rowKey="kod"
                size="small"
                pagination={false}
                dataSource={veri.data?.kayip_nedenleri ?? []}
                columns={[
                  { title: "Neden", dataIndex: "neden" },
                  { title: "Adet", dataIndex: "adet", width: 80, className: "mono" },
                ]}
              />
            )}
          </Card>
        </Col>
        {gorunum === "ekip" && (
          <Col xs={24} lg={16}>
            <Card title="Satışçı kırılımı" size="small">
              <Table
                rowKey={(r) => String(r.owner_id)}
                size="small"
                pagination={false}
                loading={veri.isLoading}
                dataSource={veri.data?.satiscilar ?? []}
                scroll={{ x: true }}
                columns={[
                  { title: "Satışçı", dataIndex: "ad" },
                  { title: "Toplam", dataIndex: "toplam", className: "mono" },
                  { title: "Açık", dataIndex: "acik", className: "mono" },
                  { title: "Kazanılan", dataIndex: "kazanilan", className: "mono" },
                  { title: "Kaybedilen", dataIndex: "kaybedilen", className: "mono" },
                  { title: "Süresi dolan", dataIndex: "suresi_dolan", className: "mono" },
                  {
                    title: "Kazanma",
                    dataIndex: "kazanma_orani",
                    className: "mono",
                    render: (x: number | null) => oran(x),
                  },
                ]}
              />
            </Card>
          </Col>
        )}
      </Row>
    </Space>
  );
}
