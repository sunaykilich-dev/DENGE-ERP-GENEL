import { useQuery } from "@tanstack/react-query";
import { Alert, Empty, Spin, Tag, Typography } from "antd";

import { api } from "../api/client";

interface Izin {
  kod: string;
  modul: string;
  aciklama: string;
}

interface Yetki {
  code: string;
  name: string;
  scope: string;
  scope_aciklama: string;
  sayfalar: string[];
  izinler: Izin[];
  istisna_kodlari: string[];
}

/**
 * Bir kişinin (ya da rolün) AÇTIĞI EKRANLAR ve verdiği izinler.
 *
 * Kullanıcı açarken rol seçmek, bu bilgi olmadan kör bir tercihti: yönetici
 * "Satış Temsilcisi" ile "Satış Müdürü" arasındaki farkı ancak kodu okuyarak
 * bilebilirdi. Bilinmeyen bir yetkinin verilmesi, gereğinden geniş yetkinin
 * en sık sebebi.
 *
 * `userId` verilirse liste o KİŞİNİN etkin yetkisidir: rolün üstüne binen
 * istisnalar dahil. Rolün ham listesini göstermek yanıltıcıydı — istisnayla
 * verilen yetki görünmez, geri alınan yetki hâlâ görünürdü.
 *
 * Liste sunucudan gelir — izin katalogu `app/permissions.py`'de tek bir yerde
 * tanımlı ve arayüzde kopyalanmaz; kopyalansaydı katalog değişince sessizce
 * yanlış bilgi gösterirdi.
 */
export default function RolYetkileri({
  rolKodu,
  userId,
}: {
  rolKodu?: string;
  userId?: number;
}) {
  // Kullanıcı görünümü yalnız KAYITLI rol için doğru: yönetici açılır menüden
  // başka bir rol seçtiyse henüz kaydedilmemiş o rolün listesi gösterilir.
  const kisisel = userId !== undefined;
  const { data, isLoading } = useQuery({
    queryKey: kisisel ? ["kullanici-yetkileri", userId] : ["rol-yetkileri", rolKodu],
    queryFn: () =>
      api.get<Yetki>(
        kisisel ? `/api/kullanicilar/${userId}/yetkiler` : `/api/roller/${rolKodu}/yetkiler`,
      ),
    enabled: kisisel || Boolean(rolKodu),
  });

  if (!kisisel && !rolKodu) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="Rol seçince erişebileceği sayfalar ve izinler burada görünür"
        style={{ margin: "8px 0" }}
      />
    );
  }
  if (isLoading || !data) return <Spin size="small" />;

  const modulller = new Map<string, Izin[]>();
  for (const i of data.izinler) {
    modulller.set(i.modul, [...(modulller.get(i.modul) ?? []), i]);
  }

  return (
    <div>
      {data.scope !== "TUMU" && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 10 }}
          title="Kayıt bazlı kısıt"
          description={data.scope_aciklama}
        />
      )}

      <Typography.Text strong style={{ fontSize: 12 }}>
        {kisisel ? "Erişebileceği sayfalar" : "Rolün açtığı sayfalar"} ({data.sayfalar.length})
      </Typography.Text>
      <div style={{ margin: "6px 0 14px" }}>
        {data.sayfalar.map((s) => (
          <Tag key={s} style={{ marginBottom: 4 }}>
            {s}
          </Tag>
        ))}
      </div>

      <Typography.Text strong style={{ fontSize: 12 }}>
        İzin verilen aksiyonlar ({data.izinler.length})
        {kisisel && data.istisna_kodlari.length > 0 && (
          <Tag color="orange" style={{ marginInlineStart: 6 }}>
            {data.istisna_kodlari.length} tanesi kişiye özel
          </Tag>
        )}
      </Typography.Text>
      <div style={{ maxHeight: 220, overflowY: "auto", marginTop: 6 }}>
        {[...modulller.entries()].map(([modul, izinler]) => (
          <div key={modul} style={{ marginBottom: 10 }}>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {modul}
            </Typography.Text>
            {izinler.map((i) => (
              <div key={i.kod} style={{ fontSize: 12, lineHeight: 1.5 }}>
                • {i.aciklama}{" "}
                <Typography.Text type="secondary" className="mono" style={{ fontSize: 10 }}>
                  {i.kod}
                </Typography.Text>
                {data.istisna_kodlari.includes(i.kod) && (
                  <Tag color="orange" style={{ marginInlineStart: 4 }}>
                    istisna
                  </Tag>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
        {kisisel
          ? 'Turuncu işaretliler rolden değil, aşağıdaki "izin istisnaları"ndan geliyor.'
          : "Bu liste rolün verdiğidir; rolü değiştirmek o roldeki herkesi etkiler."}
      </Typography.Text>
    </div>
  );
}
