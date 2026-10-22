import { DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { anaVeriApi, type BirlestirmeKaydi } from "../api/anaVeri";
import {
  adayExcelAdresi,
  eslestirmeOzeti,
  kaliteExcelAdresi,
  kaliteListesi,
  kaliteOzeti,
  type EslestirmeKaynagi,
  type EslestirmeSayilari,
  type KaliteKontrolu,
  type KaliteSatiri,
} from "../api/veriKalitesi";
import { useAuth } from "../auth/AuthContext";
import Statistic from "../components/Statistic";

/**
 * Servis Ana Verisi ve Veri Kalitesi (TS-171, TS-188, TS-192).
 *
 * - **Veri Kalitesi** (`servis_rapor.gor`): servis, müşteri/tesis, sözleşme ve
 *   ekipman kontrolleri. Ekran SALT OKUMADIR; her kutunun sayısı tıklanınca
 *   açılan listenin toplamıdır (sayı = liste = Excel). Satır kendi ekranına
 *   bağlanır (iş, hesap, sözleşme, ekipman); düzeltme orada yapılır.
 * - **Eşleştirme** (`hesap.birlestir`): serbest metin aday listesi (Excel) ve
 *   İçe Aktarma'ya bağlantı. Ekran KARAR VERMEZ ve YAZMAZ.
 * - **Birleştirme kayıtları** (`hesap.birlestir`): salt okunur geçmiş.
 */

const SAYFA = 25;

const KAYNAKLAR: { kod: EslestirmeKaynagi; baslik: string; aciklama: string }[] = [
  {
    kod: "sozlesme",
    baslik: "Bakım sözleşmeleri",
    aciklama: "Hesabı ya da tesisi boş sözleşmeler (göçten teyit bekleyenler dahil).",
  },
  {
    kod: "ekipman",
    baslik: "Güvenlik ekipmanı",
    aciklama: "Kütükte hesabı ya da tesisi boş Güvenlik ekipmanı (Faz 1).",
  },
];

/** Kontrol satırının sütunları: anahtar → başlık (sunucu Excel'iyle aynı alanlar). */
const SUTUN_ADLARI: Record<string, string> = {
  so_no: "İş no",
  birim: "Birim",
  tur: "Tür",
  durum: "Durum",
  musteri: "Müşteri",
  lokasyon: "Lokasyon",
  acilis: "Açılış",
  unvan: "Unvan",
  tesis: "Tesis",
  il: "İl",
  anahtar: "Unvan anahtarı",
  vkn: "VKN",
  adet: "Adet",
  hesaplar: "Hesaplar",
  sozlesme_no: "Sözleşme no",
  cari: "Cari",
  donem: "Dönem",
  dosya: "Dosya",
  satir_no: "Satır",
  ref: "Kaynak ref",
  hatalar: "Hatalar",
};

function Sayilar({ s }: { s: EslestirmeSayilari | undefined }) {
  const kutular: { baslik: string; deger: number | undefined; renk?: string }[] = [
    { baslik: "Eşleşmemiş", deger: s?.eslesmemis },
    { baslik: "Hesapsız", deger: s?.hesapsiz },
    { baslik: "Kesin öneri", deger: s?.kesin_oneri, renk: "#2f7d32" },
    { baslik: "Belirsiz (insana)", deger: s?.belirsiz, renk: "#b7791f" },
    { baslik: "Müşterisi boş", deger: s?.musterisiz },
  ];
  return (
    <Row gutter={[12, 12]}>
      {kutular.map((k) => (
        <Col key={k.baslik} xs={12} sm={8} md={8} lg={4}>
          <Statistic
            title={k.baslik}
            value={k.deger ?? "—"}
            valueStyle={k.renk ? { color: k.renk } : undefined}
          />
        </Col>
      ))}
    </Row>
  );
}

function KontrolListesi({ kontrol }: { kontrol: KaliteKontrolu }) {
  const { yetkili } = useAuth();
  const git = useNavigate();
  const [sayfa, setSayfa] = useState(1);
  const liste = useQuery({
    queryKey: ["veri-kalitesi-liste", kontrol.kod, sayfa],
    queryFn: () => kaliteListesi(kontrol.kod, SAYFA, (sayfa - 1) * SAYFA),
  });
  const ilk = liste.data?.kayitlar[0];
  const anahtarlar = ilk
    ? Object.keys(ilk).filter((a) => a in SUTUN_ADLARI && a !== "id")
    : ["so_no", "durum"];
  return (
    <Card
      size="small"
      title={kontrol.baslik}
      extra={
        yetkili("servis_rapor.disaaktar") && (
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => window.open(kaliteExcelAdresi(kontrol.kod), "_blank")}
          >
            Excel
          </Button>
        )
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {kontrol.tanim}
      </Typography.Paragraph>
      <Table<KaliteSatiri>
        size="small"
        rowKey={(r) => String(r.id)}
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        scroll={{ x: Math.max(480, anahtarlar.length * 120) }}
        locale={{ emptyText: <Empty description="Bu kontrolde eksik kayıt yok" /> }}
        onRow={(r) => ({
          onClick: () => r.yol && git(String(r.yol)),
          style: { cursor: r.yol ? "pointer" : undefined },
        })}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam ?? 0,
          onChange: setSayfa,
          showSizeChanger: false,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} kayıt`,
        }}
        columns={anahtarlar.map((a) => ({
          title: SUTUN_ADLARI[a],
          dataIndex: a,
          ellipsis: true,
          render: (v: unknown) =>
            v == null || v === ""
              ? "—"
              : a === "acilis"
                ? dayjs(String(v)).format("DD.MM.YYYY")
                : String(v),
        }))}
      />
    </Card>
  );
}

function VeriKalitesi() {
  const git = useNavigate();
  const [arama, setArama] = useSearchParams();
  const ozet = useQuery({ queryKey: ["veri-kalitesi"], queryFn: kaliteOzeti });
  const secili = arama.get("kontrol");
  const kontroller = ozet.data?.kontroller ?? [];
  const secilen = kontroller.find((k) => k.kod === secili);
  const payda = ozet.data?.is_paydasi;
  const musterisiz = kontroller.find((k) => k.kod === "musterisiz_is")?.deger;
  const lokasyonsuz = kontroller.find((k) => k.kod === "lokasyonsuz_is")?.deger;
  const oran = (eksik?: number) =>
    payda && eksik != null ? Math.round(((payda - eksik) / payda) * 1000) / 10 : null;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title="Veri Kalitesi"
        loading={ozet.isLoading}
        extra={
          secili && (
            <Button size="small" onClick={() => setArama({})}>
              Listeyi kapat
            </Button>
          )
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Bu ekran hiçbir veriyi değiştirmez. Kutuya tıklayınca aynı sayıda satırlı liste açılır;
          satıra tıklayınca kayıt kendi ekranında açılır ve düzeltme orada yapılır.
        </Typography.Paragraph>
        {ozet.isError && (
          <Alert type="error" showIcon title="Veri kalitesi alınamadı" description={(ozet.error as Error).message} />
        )}
        {payda != null && payda > 0 && (
          <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
            <Col xs={24} sm={12}>
              <Typography.Text>Müşterisi dolu iş oranı</Typography.Text>
              <Progress percent={oran(musterisiz) ?? 0} size="small" />
            </Col>
            <Col xs={24} sm={12}>
              <Typography.Text>Lokasyonu dolu iş oranı</Typography.Text>
              <Progress percent={oran(lokasyonsuz) ?? 0} size="small" />
            </Col>
          </Row>
        )}
        {(ozet.data?.gruplar ?? []).map((g) => {
          const kutular = kontroller.filter((k) => k.grup === g.kod);
          if (!kutular.length) return null;
          return (
            <div key={g.kod} style={{ marginBottom: 12 }}>
              <Typography.Text strong>{g.ad}</Typography.Text>
              <Row gutter={[12, 12]} style={{ marginTop: 6 }}>
                {kutular.map((k) => (
                  <Col key={k.kod} xs={12} sm={8} lg={6} xl={4}>
                    <Card
                      size="small"
                      hoverable
                      role="link"
                      tabIndex={0}
                      data-kontrol={k.kod}
                      onClick={() => (k.hedef ? git(k.hedef) : setArama({ kontrol: k.kod }))}
                      style={{
                        height: "100%",
                        borderColor: secili === k.kod ? "#b7791f" : undefined,
                      }}
                    >
                      <Statistic
                        title={<span title={k.tanim}>{k.baslik}</span>}
                        value={k.deger}
                        valueStyle={{ color: k.deger ? "#b7791f" : undefined }}
                      />
                      {k.hedef && (
                        <Tag style={{ marginTop: 4 }} color="blue">
                          Ekipman Kütüğü
                        </Tag>
                      )}
                    </Card>
                  </Col>
                ))}
              </Row>
            </div>
          );
        })}
      </Card>
      {secilen && !secilen.hedef && <KontrolListesi key={secilen.kod} kontrol={secilen} />}
    </Space>
  );
}

function Birlestirmeler() {
  const [sayfa, setSayfa] = useState(1);
  const liste = useQuery({
    queryKey: ["birlestirmeler", sayfa],
    queryFn: () => anaVeriApi.birlestirmeler(SAYFA, (sayfa - 1) * SAYFA),
  });
  return (
    <Card title="Birleştirme kayıtları" size="small">
      <Table<BirlestirmeKaydi>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        scroll={{ x: 560 }}
        locale={{ emptyText: <Empty description="Henüz birleştirme yapılmadı" /> }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam ?? 0,
          onChange: setSayfa,
          showSizeChanger: false,
        }}
        columns={[
          { title: "Tarih", dataIndex: "created_at", width: 100, render: (d: string) => dayjs(d).format("DD.MM.YYYY") },
          { title: "Tür", dataIndex: "tur", width: 100, render: (t: string) => <Tag>{t === "HESAP" ? "Müşteri" : "Lokasyon"}</Tag> },
          { title: "Kaynak → Hedef", key: "kh", width: 140, render: (_, r) => `#${r.kaynak_id} → #${r.hedef_id}` },
          {
            title: "Taşınan",
            dataIndex: "tasinan",
            render: (t: Record<string, number> | null) =>
              Object.values(t ?? {}).reduce((a, b) => a + b, 0).toLocaleString("tr-TR"),
            width: 90,
          },
          { title: "Gerekçe", dataIndex: "gerekce", ellipsis: true },
        ]}
      />
    </Card>
  );
}

export default function ServisAnaVeriPage() {
  const { yetkili } = useAuth();
  const git = useNavigate();
  const birlestirici = yetkili("hesap.birlestir");
  const kaliteci = yetkili("servis_rapor.gor");
  const ozet = useQuery({
    queryKey: ["ana-veri-eslestirme-ozet"],
    queryFn: eslestirmeOzeti,
    enabled: birlestirici,
  });

  if (!birlestirici && !kaliteci) {
    return (
      <Card title="Servis Ana Verisi">
        <Alert
          type="warning"
          showIcon
          title="Bu ekran için servis raporu ya da hesap birleştirme yetkisi gerekir."
        />
      </Card>
    );
  }

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {kaliteci && <VeriKalitesi />}

      {birlestirici && (
        <>
          <Card title="Ana Veri Kalitesi — serbest metin eşleştirme">
            <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
              Eski sistemden gelen müşteri ve tesis yazımları hesaba bağlanmadan kapsam, planlı
              bakım ve müşteri bazlı raporlar doğru çıkmaz. Sistem yalnız kesin eşleşmeyi önerir;
              benzer ad yalnız öneridir, karar sizindir.
            </Typography.Paragraph>
            <Steps
              size="small"
              responsive
              current={-1}
              items={[
                { title: "Aday listesini indir", content: "Excel, her satır bir kayıt" },
                {
                  title: "Onayla",
                  content: "Onay (E/H), gerekirse hedef hesap/tesis ya da yeni tesis adı",
                },
                { title: "İçe Aktarma'dan yükle", content: "Müşteri/Lokasyon Eşleştirme profili" },
              ]}
            />
            {ozet.isError && (
              <Alert
                style={{ marginTop: 12 }}
                type="error"
                showIcon
                title="Eşleştirme özeti alınamadı"
                description={(ozet.error as Error).message}
              />
            )}
          </Card>

          {KAYNAKLAR.map((k) => (
            <Card
              key={k.kod}
              title={k.baslik}
              loading={ozet.isLoading}
              extra={
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => window.open(adayExcelAdresi(k.kod), "_blank")}
                >
                  Aday listesi
                </Button>
              }
            >
              <Typography.Paragraph type="secondary">{k.aciklama}</Typography.Paragraph>
              <Sayilar s={ozet.data?.[k.kod]} />
            </Card>
          ))}

          {yetkili("sistem.goc") && (
            <Card title="Faz 2 aday listeleri (göç)" size="small">
              <Typography.Paragraph type="secondary">
                Hesabı/tesisi boş göç servis işleri ve Güvenlik dışı ekipman (TS-208). Liste
                birim kapsamı taşımaz; yalnız göç sorumlusu indirir.
              </Typography.Paragraph>
              <Space wrap>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => window.open(adayExcelAdresi("servis_isi"), "_blank")}
                >
                  Servis işleri
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() => window.open(adayExcelAdresi("ekipman_diger"), "_blank")}
                >
                  Diğer birimlerin ekipmanı
                </Button>
              </Space>
            </Card>
          )}

          <Card size="small">
            <Space wrap>
              <Typography.Text>
                Onaylanmış dosyayı yüklemek için İçe Aktarma ekranında
                <Typography.Text strong> Müşteri/Lokasyon Eşleştirme (göç)</Typography.Text>{" "}
                profilini seçin. Aynı dosyayı ikinci kez yüklemek hiçbir şey değiştirmez.
              </Typography.Text>
              <Button type="primary" icon={<UploadOutlined />} onClick={() => git("/ice-aktarma")}>
                İçe Aktarma
              </Button>
            </Space>
          </Card>

          <Birlestirmeler />
        </>
      )}
    </Space>
  );
}
