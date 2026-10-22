import { DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Row, Space, Steps, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import {
  adayExcelAdresi,
  eslestirmeOzeti,
  type EslestirmeKaynagi,
  type EslestirmeSayilari,
} from "../api/veriKalitesi";
import { useAuth } from "../auth/AuthContext";
import Statistic from "../components/Statistic";

/**
 * Ana Veri Kalitesi (TS-171, E14-09 Faz 1).
 *
 * Eski sistemden serbest metinle gelen müşteri/tesis yazımlarını hesaba ve
 * tesise bağlamanın ekranı. Ekran KARAR VERMEZ ve YAZMAZ: aday listesini
 * (Excel) indirir, karar dosyası İçe Aktarma'dan `musteri_eslestirme`
 * profiliyle yüklenir — önizleme, karantina ve denetim izi oradadır.
 * Sayılar indirilen listeyle aynı sorgudan gelir (sayı = liste).
 */

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

export default function ServisAnaVeriPage() {
  const { yetkili } = useAuth();
  const git = useNavigate();
  const izinli = yetkili("hesap.birlestir");
  const ozet = useQuery({
    queryKey: ["ana-veri-eslestirme-ozet"],
    queryFn: eslestirmeOzeti,
    enabled: izinli,
  });

  if (!izinli) {
    return (
      <Card title="Ana Veri Kalitesi">
        <Alert type="warning" showIcon title="Bu ekran için hesap birleştirme yetkisi gerekir." />
      </Card>
    );
  }

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
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

      <Card size="small">
        <Space wrap>
          <Typography.Text>
            Onaylanmış dosyayı yüklemek için İçe Aktarma ekranında
            <Typography.Text strong> Müşteri/Lokasyon Eşleştirme (göç)</Typography.Text> profilini
            seçin. Aynı dosyayı ikinci kez yüklemek hiçbir şey değiştirmez.
          </Typography.Text>
          <Button type="primary" icon={<UploadOutlined />} onClick={() => git("/ice-aktarma")}>
            İçe Aktarma
          </Button>
        </Space>
      </Card>
    </Space>
  );
}
