/**
 * Benim İşlerim — teknisyenin tek mobil ekranı (TS-077/078, E09-D01).
 *
 * Tek sayfa, iki sekme: "İşlerim" (GECIKEN/BUGÜN/YARIN/SONRA/PLANSIZ grupları,
 * aynı gün + tesis tek ziyaret kartı, her iş ayrı seçilir) ve "Bugünüm"
 * (yalnız kendi bölümlerim, kişi-saat, mola hariç, gün sonu süre eksik
 * listesi). Ayrı "Ziyaretlerim" sayfası yok.
 *
 * Dar ekran (375 px; yan menü 56 px + dolgu → ~279 px içerik): tablo yok,
 * her şey dikey; uzun metin kırılır; ana düğmeler ≥ 44 px. Bağlantı yoksa
 * sayaç düğmeleri kilitli (çevrimdışı yok).
 *
 * Kayıt yoksa süre "Süre kaydı eksik" yazılır — "0 dk" DEĞİL.
 */
import { EditOutlined, ReloadOutlined, RightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Empty,
  List,
  Segmented,
  Space,
  Spin,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { ManuelKayitPenceresi } from "../components/SayacDugmeleri";
import SlaEtiketi from "../components/SlaEtiketi";
import Statistic from "../components/Statistic";
import {
  FAALIYET_ADLARI,
  SURE_DURUMU_ADLARI,
  servisZaman,
  sureMetni,
  type MobilIs,
  type Ziyaret,
} from "../api/servisZaman";

const GRUP_RENGI: Record<string, string> = {
  GECIKEN: "red",
  BUGUN: "blue",
  YARIN: "geekblue",
  SONRA: "default",
  PLANSIZ: "default",
};

const ONCELIK_RENGI: Record<string, string> = { KRITIK: "red", YUKSEK: "orange" };

function IsSatiri({ is }: { is: MobilIs }) {
  return (
    <Link to={`/benim-islerim/${is.id}`} style={{ display: "block", color: "inherit" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minHeight: 44 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={4} wrap>
            <Typography.Text strong>{is.so_no}</Typography.Text>
            <Tag style={{ marginInlineEnd: 0 }}>{is.durum.replaceAll("_", " ")}</Tag>
            {ONCELIK_RENGI[is.oncelik] && <Tag color={ONCELIK_RENGI[is.oncelik]}>{is.oncelik}</Tag>}
            {!is.bana_atanmis && <Tag color="purple">ekip</Tag>}
            <SlaEtiketi sla={is.sla} />
          </Space>
          <Typography.Paragraph
            style={{ margin: 0, fontSize: 13, overflowWrap: "anywhere" }}
            ellipsis={{ rows: 2 }}
          >
            {is.konu}
          </Typography.Paragraph>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {is.plan_baslangic ? dayjs(is.plan_baslangic).format("HH:mm") + " · " : ""}
            {is.sure_durumu === "EKSIK"
              ? "Süre kaydı eksik"
              : sureMetni(is.kisi_saat_dk) ?? SURE_DURUMU_ADLARI[is.sure_durumu ?? ""] ?? ""}
          </Typography.Text>
        </div>
        <RightOutlined style={{ color: "#999" }} />
      </div>
    </Link>
  );
}

function ZiyaretKarti({ z }: { z: Ziyaret }) {
  const baslik = [z.musteri, z.lokasyon].filter(Boolean).join(" · ") || "Lokasyon belirtilmemiş";
  return (
    <Card
      size="small"
      style={{ marginBottom: 8 }}
      title={
        <div style={{ whiteSpace: "normal", overflowWrap: "anywhere", lineHeight: 1.3 }}>
          {baslik}
          <div style={{ fontWeight: 400, fontSize: 12, color: "#888" }}>
            {[z.ilce, z.il].filter(Boolean).join(" / ")}
            {z.plan_tarihi ? ` · ${dayjs(z.plan_tarihi).format("DD.MM.YYYY")}` : ""}
            {z.isler.length > 1 ? ` · ${z.isler.length} iş` : ""}
          </div>
        </div>
      }
    >
      <List
        size="small"
        dataSource={z.isler}
        rowKey="id"
        renderItem={(is) => (
          <List.Item style={{ paddingInline: 0 }}>
            <div style={{ width: "100%" }}>
              <IsSatiri is={is} />
            </div>
          </List.Item>
        )}
      />
    </Card>
  );
}

function Islerim() {
  const { yetkili } = useAuth();
  const [gorunum, setGorunum] = useState<"benim" | "tumu">("benim");
  const liste = useQuery({
    queryKey: ["benim-islerim", gorunum],
    queryFn: () => servisZaman.benimIslerim(gorunum),
    refetchInterval: 60_000,
  });
  const gruplar = liste.data?.gruplar ?? [];
  const bos = gruplar.every((g) => g.ziyaretler.length === 0);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        {yetkili("servis.planla") && (
          <Segmented
            value={gorunum}
            onChange={(v) => setGorunum(v as "benim" | "tumu")}
            options={[
              { value: "benim", label: "Bana atananlar" },
              { value: "tumu", label: "Tümü (birimim)" },
            ]}
          />
        )}
        <Button icon={<ReloadOutlined />} onClick={() => void liste.refetch()}>
          Yenile
        </Button>
      </Space>
      {liste.isError && <Alert type="error" showIcon title={(liste.error as Error).message} />}
      {liste.data?.kesildi && (
        <Alert type="warning" showIcon title="Liste uzun; yalnız ilk 500 iş gösteriliyor." />
      )}
      {liste.isLoading ? (
        <Spin />
      ) : bos ? (
        <Empty description="Açık işiniz yok" />
      ) : (
        gruplar
          .filter((g) => g.ziyaretler.length > 0)
          .map((g) => (
            <div key={g.kod}>
              <Typography.Title level={5} style={{ margin: "4px 0 8px" }}>
                <Tag color={GRUP_RENGI[g.kod]}>{g.baslik}</Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {g.ziyaretler.reduce((n, z) => n + z.isler.length, 0)} iş
                </Typography.Text>
              </Typography.Title>
              {g.ziyaretler.map((z) => (
                <ZiyaretKarti key={z.anahtar} z={z} />
              ))}
            </div>
          ))
      )}
    </Space>
  );
}

function Bugunum() {
  const [gun, setGun] = useState<Dayjs>(dayjs());
  const [elle, setElle] = useState<{ id: number; so_no: string } | null>(null);
  const gunMetni = gun.format("YYYY-MM-DD");
  const ozet = useQuery({
    queryKey: ["bugunum", gunMetni],
    queryFn: () => servisZaman.bugunum(gunMetni),
  });
  const v = ozet.data;
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <DatePicker
        value={gun}
        format="DD.MM.YYYY"
        allowClear={false}
        onChange={(d) => d && setGun(d)}
        disabledDate={(d) => d.isAfter(dayjs(), "day") || d.isBefore(dayjs().subtract(31, "day"))}
        style={{ width: "100%", maxWidth: 220 }}
      />
      {ozet.isError && <Alert type="error" showIcon title={(ozet.error as Error).message} />}
      {v && (
        <>
          <Card size="small">
            <Space wrap size={[24, 8]}>
              {v.kisi_saat_dk === null ? (
                <Statistic title="Kişi-saat" value="Kayıt yok" />
              ) : (
                <Statistic title="Kişi-saat" value={sureMetni(v.kisi_saat_dk) ?? ""} />
              )}
              {Object.entries(v.faaliyet_dk).map(([f, dk]) => (
                <Statistic
                  key={f}
                  title={FAALIYET_ADLARI[f as keyof typeof FAALIYET_ADLARI] ?? f}
                  value={sureMetni(dk) ?? ""}
                />
              ))}
              {v.mola_dk !== null && (
                <Statistic title="Mola (hariç)" value={sureMetni(v.mola_dk) ?? ""} />
              )}
            </Space>
          </Card>

          <Card size="small" title="Süre kaydı eksik işler">
            {v.sure_eksik_isler.length === 0 ? (
              <Typography.Text type="secondary">Eksik kayıt yok.</Typography.Text>
            ) : (
              <List
                size="small"
                dataSource={v.sure_eksik_isler}
                rowKey="id"
                renderItem={(i) => (
                  <List.Item
                    style={{ paddingInline: 0, flexWrap: "wrap", gap: 8 }}
                    actions={[
                      <Button
                        key="elle"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => setElle({ id: i.id, so_no: i.so_no })}
                      >
                        Elle gir
                      </Button>,
                    ]}
                  >
                    <div style={{ minWidth: 0 }}>
                      <Link to={`/benim-islerim/${i.id}`}>{i.so_no}</Link>{" "}
                      <Tag color="red">Süre kaydı eksik</Tag>
                      <div style={{ fontSize: 12, overflowWrap: "anywhere" }}>{i.konu}</div>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </Card>

          <Card size="small" title="Bölümler">
            {v.bolumler.length === 0 ? (
              <Typography.Text type="secondary">Bu gün kayıt yok.</Typography.Text>
            ) : (
              <Timeline
                items={v.bolumler.map((b) => ({
                  color: b.iptal_turu ? "gray" : b.faaliyet === "MOLA" ? "orange" : "blue",
                  content: (
                    <div style={{ opacity: b.iptal_turu ? 0.55 : 1 }}>
                      <Typography.Text strong>
                        {dayjs(b.started_at).format("HH:mm")}–
                        {b.ended_at ? dayjs(b.ended_at).format("HH:mm") : "…"}
                      </Typography.Text>{" "}
                      {FAALIYET_ADLARI[b.faaliyet]} · {b.so_no}
                      {b.sure_dk !== null && ` · ${sureMetni(b.sure_dk)}`}
                      {b.kaynak !== "CANLI" && (
                        <Tag style={{ marginInlineStart: 6 }}>{b.kaynak.replaceAll("_", " ").toLowerCase()}</Tag>
                      )}
                      {b.iptal_turu && <Tag>{b.iptal_turu === "GERI_ALINDI" ? "geri alındı" : "iptal"}</Tag>}
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </>
      )}
      <ManuelKayitPenceresi
        acik={!!elle}
        isId={elle?.id ?? null}
        soNo={elle?.so_no}
        onKapat={() => setElle(null)}
      />
    </Space>
  );
}

export default function BenimIslerimPage() {
  const [params, setParams] = useSearchParams();
  const sekme = params.get("sekme") === "bugunum" ? "bugunum" : "islerim";
  return (
    <div style={{ maxWidth: 720 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Benim İşlerim
      </Typography.Title>
      <Tabs
        activeKey={sekme}
        onChange={(k) => setParams(k === "bugunum" ? { sekme: "bugunum" } : {})}
        items={[
          { key: "islerim", label: "İşlerim", children: <Islerim /> },
          { key: "bugunum", label: "Bugünüm", children: <Bugunum /> },
        ]}
      />
    </div>
  );
}
