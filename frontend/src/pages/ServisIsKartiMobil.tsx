/**
 * Servis İşi Kartı — tek sayfa mobil iş kartı (TS-077).
 *
 * Teknisyenin sahada ihtiyacı olan her şey tek ekranda: müşteri/tesis, adres
 * (harita bağlantısı YALNIZ dokunulunca açılır; konum kaydedilmez, K3),
 * saha yetkilisi (`tel:`; telefon izinsizde maskeli), seri, plan ve ulaşım
 * notu, süre özeti, sayaç düğmeleri, kamera ile ek (`capture`), "Sonuç Gir"
 * ve PB'de "Bakım Formu". FİYAT/MALİYET ALANI YOK (sunucu da döndürmez).
 *
 * Açık sayaç bu işteyken "Sonuç Gir" önce sayacı bitirmeyi önerir: açık
 * sayaçlı iş tamamlanamaz (sunucu 409, TS-073).
 */
import {
  ArrowLeftOutlined,
  EnvironmentOutlined,
  PhoneOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, Space, Spin, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import EkYukleyici from "../components/EkYukleyici";
import SayacDugmeleri, { ManuelKayitPenceresi } from "../components/SayacDugmeleri";
import SlaEtiketi from "../components/SlaEtiketi";
import { SURE_DURUMU_ADLARI, servisZaman, sureMetni } from "../api/servisZaman";

export default function ServisIsKartiMobil() {
  const { id } = useParams();
  const isId = Number(id);
  const navigate = useNavigate();
  const { yetkili } = useAuth();
  const [elle, setElle] = useState(false);

  const kart = useQuery({
    queryKey: ["mobil-kart", isId],
    queryFn: () => servisZaman.kart(isId),
    enabled: Number.isFinite(isId),
    refetchInterval: 30_000,
  });
  // Aynı ziyaretteki diğer işler ("Sonraki Cihaza Geç" önerisi).
  const liste = useQuery({
    queryKey: ["benim-islerim", "benim"],
    queryFn: () => servisZaman.benimIslerim("benim"),
  });

  if (kart.isLoading) return <Spin />;
  if (kart.isError || !kart.data) {
    return (
      <Space orientation="vertical">
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/benim-islerim")}>
          Benim İşlerim
        </Button>
        <Empty description={(kart.error as Error | null)?.message ?? "İş bulunamadı"} />
      </Space>
    );
  }
  const k = kart.data;
  const ziyaret = liste.data?.gruplar
    .flatMap((g) => g.ziyaretler)
    .find((z) => z.isler.some((i) => i.id === k.id));
  const sonrakiIsler = (ziyaret?.isler ?? [])
    .filter((i) => i.id !== k.id && i.sayac_acilabilir && i.bana_atanmis)
    .map((i) => ({ id: i.id, so_no: i.so_no }));
  const adresMetni = [k.lokasyon, k.adres].filter(Boolean).join(", ");
  const haritaUrl = adresMetni
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(adresMetni)}`
    : null;
  const ozet = k.sure_ozeti;

  return (
    <div style={{ maxWidth: 720 }}>
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        style={{ paddingInline: 0 }}
        onClick={() => navigate("/benim-islerim")}
      >
        Benim İşlerim
      </Button>
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Card size="small">
          <Space size={6} wrap>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {k.so_no}
            </Typography.Title>
            <Tag>{k.durum.replaceAll("_", " ")}</Tag>
            <Tag color="blue">{k.tur}</Tag>
            {k.oncelik !== "NORMAL" && <Tag color="red">{k.oncelik}</Tag>}
            <SlaEtiketi sla={k.sla} kisa={false} />
          </Space>
          <Typography.Paragraph style={{ margin: "6px 0 0", overflowWrap: "anywhere" }}>
            {k.konu}
          </Typography.Paragraph>
          {k.aciklama && (
            <Typography.Paragraph
              type="secondary"
              style={{ fontSize: 13, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              ellipsis={{ rows: 4, expandable: true, symbol: "devamı" }}
            >
              {k.aciklama}
            </Typography.Paragraph>
          )}
        </Card>

        <Card size="small" title="Sayaç">
          <SayacDugmeleri
            isId={k.id}
            sayac={k}
            baslatilabilir={k.sayac_acilabilir && k.bana_atanmis}
            sonrakiIsler={sonrakiIsler}
          />
        </Card>

        <Card size="small" title="Müşteri ve saha">
          <Space orientation="vertical" size={6} style={{ width: "100%" }}>
            <Typography.Text strong style={{ overflowWrap: "anywhere" }}>
              {k.musteri ?? "—"}
            </Typography.Text>
            {k.lokasyon && <Typography.Text style={{ overflowWrap: "anywhere" }}>{k.lokasyon}</Typography.Text>}
            {k.adres && (
              <Typography.Text type="secondary" style={{ overflowWrap: "anywhere" }}>
                {k.adres}
              </Typography.Text>
            )}
            {haritaUrl && (
              <a href={haritaUrl} target="_blank" rel="noreferrer">
                <Button icon={<EnvironmentOutlined />} style={{ minHeight: 44 }}>
                  Haritada aç
                </Button>
              </a>
            )}
            {k.ulasim_notu && (
              <Alert type="info" showIcon title="Ulaşım notu" description={k.ulasim_notu} />
            )}
            {(k.irtibat_ad || k.irtibat_telefon) && (
              <div>
                <Typography.Text>{k.irtibat_ad ?? "Saha yetkilisi"}</Typography.Text>{" "}
                {k.irtibat_telefon &&
                  (k.telefon_maskeli ? (
                    <Typography.Text type="secondary">{k.irtibat_telefon}</Typography.Text>
                  ) : (
                    <a href={`tel:${k.irtibat_telefon}`}>
                      <Button icon={<PhoneOutlined />} style={{ minHeight: 44 }}>
                        {k.irtibat_telefon}
                      </Button>
                    </a>
                  ))}
              </div>
            )}
          </Space>
        </Card>

        <Card size="small" title="İş bilgisi">
          <Descriptions column={1} size="small">
            {k.seriler.length > 0 && (
              <Descriptions.Item label="Seri">
                <span style={{ overflowWrap: "anywhere" }}>{k.seriler.join(", ")}</span>
              </Descriptions.Item>
            )}
            {k.plan && (
              <Descriptions.Item label="Plan">
                {dayjs(k.plan.plan_tarihi).format("DD.MM.YYYY")}
                {k.plan.baslangic ? ` ${dayjs(k.plan.baslangic).format("HH:mm")}` : ""} ·{" "}
                {sureMetni(k.plan.sure_dk)}
              </Descriptions.Item>
            )}
            {k.plan?.plan_notu && (
              <Descriptions.Item label="Plan notu">{k.plan.plan_notu}</Descriptions.Item>
            )}
            {k.plan?.saha_alani && (
              <Descriptions.Item label="Saha alanı">{k.plan.saha_alani}</Descriptions.Item>
            )}
            {k.plan?.saha_notu && (
              <Descriptions.Item label="Saha notu">{k.plan.saha_notu}</Descriptions.Item>
            )}
            <Descriptions.Item label="Süre">
              {ozet.kisi_saat_dk === null ? (
                ozet.sure_durumu === "BEKLENMIYOR" ? (
                  "—"
                ) : (
                  <Tag color="red">Süre kaydı eksik</Tag>
                )
              ) : (
                <>
                  {sureMetni(ozet.kisi_saat_dk)}{" "}
                  <Tag color={ozet.sure_durumu === "TAM" ? "green" : "orange"}>
                    {SURE_DURUMU_ADLARI[ozet.sure_durumu]}
                  </Tag>
                </>
              )}
              {ozet.mola_dk !== null && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {" "}
                  · Mola {sureMetni(ozet.mola_dk)} (hariç)
                </Typography.Text>
              )}
            </Descriptions.Item>
            {ozet.eksik_kisiler.length > 0 && (
              <Descriptions.Item label="Kaydı eksik">{ozet.eksik_kisiler.join(", ")}</Descriptions.Item>
            )}
          </Descriptions>
          {k.bana_atanmis && (
            <Button size="small" onClick={() => setElle(true)}>
              Elle süre gir
            </Button>
          )}
        </Card>

        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          {k.acik_bolum_bu_iste && (
            <Alert
              type="warning"
              showIcon
              title="Sonuç girmeden önce sayacı bitirin"
              description="Açık sayaçlı iş tamamlanamaz."
            />
          )}
          {yetkili("servis.tamamla") && (
            <Link to={`/servis-isleri/${k.id}`}>
              <Button type="primary" block size="large" style={{ minHeight: 44 }}>
                Sonuç Gir
              </Button>
            </Link>
          )}
          {k.bakim_formu && (
            <Link to={`/bakim?is=${k.id}`}>
              <Button block size="large" style={{ minHeight: 44 }}>
                Bakım Formu
              </Button>
            </Link>
          )}
        </Space>

        <EkYukleyici
          entity="service_orders"
          entityId={k.id}
          kind="SERVIS_SONRASI"
          baslik="Fotoğraf / ek"
          aciklama="Kamera ile çekip doğrudan yükleyebilirsiniz."
          yazabilir={k.bana_atanmis && yetkili("servis.yaz")}
          yalnizTur={false}
          accept="image/*,application/pdf"
          capture="environment"
        />
      </Space>
      <ManuelKayitPenceresi
        acik={elle}
        isId={k.id}
        soNo={k.so_no}
        onKapat={() => setElle(false)}
      />
    </div>
  );
}
