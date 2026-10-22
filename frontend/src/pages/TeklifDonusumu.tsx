/**
 * Birimli (servis) teklif dönüşüm raporu — çekmece (TS-197, E07-24).
 *
 * Kabul oranı karara bağlanmış tekliflerden: kaybedilen = ret + hesaplanan
 * "süresi doldu"; iptal kaybedilen sayılmaz, ayrı gösterilir. Revizyon aynı
 * teklifin sürümüdür (bir kez sayılır). Satış teklif raporu (`/raporlar`)
 * değişmez. İzin `teklif.gor + servis_rapor.gor`; Excel ayrıca
 * `servis_rapor.disaaktar`. Anlamlı oran için onay akışının 2–3 ay çalışmış
 * olması gerekir.
 */
import { DownloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Select, Space, Table, Typography } from "antd";
import { useState } from "react";

import { BIRIM_ETIKETLERI } from "../api/personel";
import { servisMaliyetApi, tl } from "../api/servisMaliyet";
import { useAuth } from "../auth/AuthContext";

const DURUMLAR: Record<string, string> = {
  TASLAK: "Taslak",
  ONAY_BEKLIYOR: "Onay bekliyor",
  ONAYLANDI: "Onaylandı",
  GONDERILDI: "Gönderildi",
  GORUNTULENDI: "Görüntülendi",
  REVIZE_EDILDI: "Revize edildi",
  KABUL: "Kabul",
  RED: "Ret",
  SURESI_DOLDU: "Süresi doldu",
  SIPARISE_DONUSTU: "Siparişe dönüştü",
  IPTAL: "İptal",
};

export default function TeklifDonusumu({
  acik,
  onKapat,
  birimler,
}: {
  acik: boolean;
  onKapat: () => void;
  birimler: string[];
}) {
  const { yetkili } = useAuth();
  const [birim, setBirim] = useState<string | undefined>(birimler[0]);
  const [gun, setGun] = useState(365);
  const rapor = useQuery({
    queryKey: ["teklif-donusumu", birim, gun],
    queryFn: () => servisMaliyetApi.teklifDonusumu(birim!, gun),
    enabled: acik && !!birim,
  });
  const d = rapor.data;
  return (
    <Drawer open={acik} onClose={onKapat} title="Servis teklif dönüşümü" size={560}>
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Space wrap>
          <Select
            style={{ width: 200 }}
            value={birim}
            onChange={setBirim}
            options={birimler.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))}
          />
          <Select
            style={{ width: 140 }}
            value={gun}
            onChange={setGun}
            options={[90, 180, 365, 730].map((g) => ({ value: g, label: `Son ${g} gün` }))}
          />
          {birim && yetkili("servis_rapor.disaaktar") && (
            <Button
              icon={<DownloadOutlined />}
              onClick={() =>
                window.open(servisMaliyetApi.teklifDonusumuExcelAdresi(birim, gun), "_blank")
              }
            >
              Excel
            </Button>
          )}
        </Space>
        {rapor.isError && <Alert type="error" message={(rapor.error as Error).message} />}
        {d && (
          <>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Toplam teklif">{d.toplam_teklif}</Descriptions.Item>
              <Descriptions.Item label="Gönderilen">{d.gonderilen_adet}</Descriptions.Item>
              <Descriptions.Item label="Kazanılan">{d.kazanilan}</Descriptions.Item>
              <Descriptions.Item label="Kaybedilen (ret + süresi dolan)">
                {d.kaybedilen}
              </Descriptions.Item>
              <Descriptions.Item label="İptal (kaybedilen sayılmaz)">{d.iptal}</Descriptions.Item>
              <Descriptions.Item label="Dönüşüm oranı">
                {d.donusum_yuzde === null
                  ? "karara bağlanan teklif yok"
                  : `%${d.donusum_yuzde.toLocaleString("tr-TR")}`}
              </Descriptions.Item>
              {yetkili("teklif.gor") && (
                <Descriptions.Item label="Kabul tutarı (KDV hariç)">
                  {tl(d.kabul_tutari_net)}
                  {d.kabul_tutari_eksik > 0 && ` (${d.kabul_tutari_eksik} teklifte kur eksik)`}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="Ortalama yanıt (gün)">
                {d.ort_yanit_gun ?? "—"}
              </Descriptions.Item>
            </Descriptions>
            <Table
              size="small"
              rowKey="durum"
              pagination={false}
              title={() => "Durum dağılımı"}
              dataSource={Object.entries(d.durumlar).map(([durum, adet]) => ({ durum, adet }))}
              columns={[
                { title: "Durum", dataIndex: "durum", render: (v: string) => DURUMLAR[v] ?? v },
                { title: "Adet", dataIndex: "adet", width: 80 },
              ]}
            />
            {d.kayip_nedenleri.length > 0 && (
              <Table
                size="small"
                rowKey="neden"
                pagination={false}
                title={() => "Ret nedenleri"}
                dataSource={d.kayip_nedenleri}
                columns={[
                  { title: "Neden", dataIndex: "neden" },
                  { title: "Adet", dataIndex: "adet", width: 80 },
                ]}
              />
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Süresi geçen ve karar bekleyen teklif "süresi doldu" sayılır (hesaplanır).
            </Typography.Text>
          </>
        )}
      </Space>
    </Drawer>
  );
}
