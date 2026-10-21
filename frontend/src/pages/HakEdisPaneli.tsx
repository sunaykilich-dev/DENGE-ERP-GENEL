import { CheckCircleOutlined, DownloadOutlined, WarningOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Progress,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api } from "../api/client";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

/**
 * Hak ediş dönem paneli — canlı uygulamadaki "ay özeti" ekranının karşılığı.
 *
 * Dökümler oluşmadan ÖNCE bakılır. Buradaki her uyarı hak edişin eksik ya da
 * fazla ödenmesine yol açar; döküm çıkıp ödendikten sonra düzeltmek pahalıdır,
 * çünkü kapanmış dönem değişmez — düzeltme sonraki aya ayrı satır olarak girer.
 */

interface Panel {
  donem: string;
  ziyaret: number;
  kalem: number;
  odenecek_kalem: number;
  odenmeyecek_kalem: number;
  karar_bekleyen: number;
  tutar: string;
  yol_tutari: string;
  genel_toplam: string;
  aktif_nokta: number;
  noktalar: { partner_id: number | null; unvan: string; tutar: string }[];
  is_tipleri: { tip: string; adet: number }[];
  kontroller: { ad: string; adet: number; aciklama: string }[];
}

const tl = (v: string | number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const TIP_ADI: Record<string, string> = {
  ATS_MONTAJ: "ATS montajı",
  OBD_ATS_MONTAJ: "OBD'li ATS montajı",
  DASHCAM_MONTAJ: "Dashcam montajı",
  HARICI_KAMERA_MONTAJ: "Harici kamera montajı",
  SOKUM: "Söküm",
  SOK_TAK: "Sök-tak",
  DEGISIM: "Değişim",
  ARIZA: "Arıza",
  KESIF: "Keşif",
};

const TIP_RENGI: Record<string, string> = {
  ATS_MONTAJ: "#11417f",
  OBD_ATS_MONTAJ: "#5b7fb8",
  DASHCAM_MONTAJ: "#b58105",
  HARICI_KAMERA_MONTAJ: "#3361a1",
  SOKUM: "#7a8394",
};

export default function HakEdisPaneli() {
  const { yetkili } = useAuth();
  const [donem, setDonem] = useState(dayjs().format("YYYY-MM"));

  const panel = useQuery({
    queryKey: ["hakedis-panel", donem],
    queryFn: () => api.get<Panel>(`/api/hakedis/panel/${donem}`),
    enabled: /^\d{4}-\d{2}$/.test(donem),
  });

  const p = panel.data;
  const enYuksek = Math.max(1, ...(p?.noktalar ?? []).map((n) => Number(n.tutar)));

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <Input
          value={donem}
          onChange={(e) => setDonem(e.target.value.trim())}
          placeholder="2026-06"
          className="mono"
          style={{ width: 140 }}
        />
        <Typography.Text type="secondary">
          Dökümler oluşturulmadan önce bu ekrana bakın.
        </Typography.Text>
        {yetkili("rapor.disaaktar") && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => window.open(`/api/hakedis/donem/${donem}/excel`, "_blank")}
          >
            Bu ayı Excel'e aktar
          </Button>
        )}
      </Space>

      {p && p.kalem === 0 && (
        <Empty description={`${p.donem} döneminde kayıt yok. "Yeni montaj / söküm" ile iş girin.`} />
      )}

      {p && p.kalem > 0 && (
        <>
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Card loading={panel.isLoading}>
                <Statistic title="Ziyaret" value={p.ziyaret} />
                <Typography.Text type="secondary">{p.kalem} cihaz kalemi</Typography.Text>
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card loading={panel.isLoading}>
                <Statistic
                  title="Ödenecek hak ediş"
                  value={p.genel_toplam}
                  formatter={(v) => tl(Number(v))}
                  valueStyle={{ color: "#1f6b4d" }}
                />
                <Typography.Text type="secondary">
                  {p.odenecek_kalem} kalem + {tl(p.yol_tutari)} yol
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card loading={panel.isLoading}>
                <Statistic
                  title="Ödenmeyecek"
                  value={p.odenmeyecek_kalem}
                  valueStyle={p.karar_bekleyen ? undefined : { color: "#7a8394" }}
                />
                <Typography.Text type="secondary">Hak edişe girmez</Typography.Text>
              </Card>
            </Col>
            <Col xs={12} md={6}>
              <Card loading={panel.isLoading}>
                <Statistic title="Aktif montaj noktası" value={p.aktif_nokta} />
                <Typography.Text type="secondary">Bu ay iş yapan</Typography.Text>
              </Card>
            </Col>
          </Row>

          {p.karar_bekleyen > 0 && (
            <Alert
              type="warning"
              showIcon
              title={`${p.karar_bekleyen} kalem karar bekliyor`}
              description="Ödenecek mi ödenmeyecek mi işaretlenmeden bu kalemler döküme GİRMEZ. Ay kapanmadan karara bağlayın."
            />
          )}

          {p.kontroller.length > 0 ? (
            <Card
              title={
                <Space>
                  <WarningOutlined style={{ color: "#b58105" }} />
                  {p.donem} — gözden geçirilmesi gerekenler
                </Space>
              }
              style={{ borderColor: "#e3c77a" }}
            >
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                Ay kapanmadan bakın; bunlar hak edişin eksik ya da fazla ödenmesine yol açabilir.
                Döküm ödendikten sonra satırlar kilitlenir ve düzeltme ancak sonraki döneme ayrı
                bir satır olarak girebilir.
              </Typography.Paragraph>
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                {p.kontroller.map((k) => (
                  <div
                    key={k.ad}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 16,
                      alignItems: "baseline",
                    }}
                  >
                    <Space orientation="vertical" size={0}>
                      <Typography.Text strong>{k.ad}</Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {k.aciklama}
                      </Typography.Text>
                    </Space>
                    <Tag color="orange" style={{ flexShrink: 0 }}>
                      {k.adet}
                    </Tag>
                  </div>
                ))}
              </Space>
            </Card>
          ) : (
            <Alert
              type="success"
              showIcon
              icon={<CheckCircleOutlined />}
              title={`${p.donem} kayıtlarında gözden geçirilmesi gereken bir şey yok.`}
            />
          )}

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <Card title="Montaj noktalarına göre ödenecek tutar">
                {p.noktalar.length === 0 ? (
                  <Empty description="Bu ay ödenecek iş yok" />
                ) : (
                  <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                    {p.noktalar.slice(0, 10).map((n) => (
                      <div key={`${n.partner_id}`}>
                        <Space
                          style={{ width: "100%", justifyContent: "space-between" }}
                          align="baseline"
                        >
                          <Typography.Text ellipsis style={{ maxWidth: 280 }}>
                            {n.unvan}
                          </Typography.Text>
                          <Typography.Text strong className="tutar">
                            {tl(n.tutar)}
                          </Typography.Text>
                        </Space>
                        <Progress
                          percent={Math.round((Number(n.tutar) / enYuksek) * 100)}
                          showInfo={false}
                          size="small"
                          strokeColor="#11417f"
                        />
                      </div>
                    ))}
                    {p.noktalar.length > 10 && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        En yüksek 10 nokta gösteriliyor ({p.noktalar.length} nokta var).
                      </Typography.Text>
                    )}
                  </Space>
                )}
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card title="İş tipi dağılımı">
                <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                  {p.is_tipleri.map((t) => (
                    <div key={t.tip}>
                      <Space style={{ width: "100%", justifyContent: "space-between" }}>
                        <Typography.Text>{TIP_ADI[t.tip] ?? t.tip}</Typography.Text>
                        <Typography.Text className="mono">
                          {t.adet.toLocaleString("tr-TR")}
                        </Typography.Text>
                      </Space>
                      <Progress
                        percent={Math.round((t.adet / p.kalem) * 100)}
                        showInfo={false}
                        size="small"
                        strokeColor={TIP_RENGI[t.tip] ?? "#7a8394"}
                      />
                    </div>
                  ))}
                </Space>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </Space>
  );
}
