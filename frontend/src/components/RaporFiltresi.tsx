import { Button, DatePicker, Input, InputNumber, Select, Space } from "antd";
import dayjs, { type Dayjs } from "dayjs";

import { BIRIM_ETIKETLERI } from "../api/personel";
import type { RaporFiltresiDegeri } from "../api/servisRaporlari";
import { useAuth } from "../auth/AuthContext";

/**
 * Servis raporlarının ortak filtre çubuğu — TS-181.
 *
 * Tarih aralığı + hazır düğmeler, tarih esası, kategori, birim (yalnız
 * kullanıcının birimleri; TÜMÜ kapsamında hepsi), durum grubu, öncelik,
 * şehir ve (isteğe bağlı) tekrar arıza penceresi. Değer URL'de tutulur;
 * doğrulama SUNUCUDADIR (katalog dışı 422, tarih sırası / 24 ay 400,
 * yetkisiz birim 403) — bileşen yalnız seçenek sunar.
 */
/** İskelet adı (D3-S) — diğer ekranlar (Zaman Takibi) aynı tipi kullanır. */
export type RaporFiltreDegeri = RaporFiltresiDegeri;

export interface RaporFiltresiProps {
  deger: RaporFiltresiDegeri;
  degisti: (yeni: RaporFiltresiDegeri) => void;
  /** Tekrar arıza sekmesinde pencere (7–180 gün) girişi. */
  tekrarGun?: boolean;
}

const ISO = "YYYY-MM-DD";

const KATEGORILER = [
  { value: "GUNLUK_SERVIS", label: "Günlük Servis" },
  { value: "PLANLI_BAKIM", label: "Planlı Bakım" },
  { value: "ATOLYE", label: "Atölye" },
  { value: "PROJE", label: "Proje" },
];
const DURUM_GRUPLARI = [
  { value: "ACIK", label: "Açık" },
  { value: "COZULDU", label: "Çözüldü" },
  { value: "IPTAL", label: "İptal" },
];
const ONCELIKLER = [
  { value: "KRITIK", label: "Kritik" },
  { value: "YUKSEK", label: "Yüksek" },
  { value: "NORMAL", label: "Normal" },
];
const TARIH_ESASLARI = [
  { value: "ACILIS", label: "Açılış tarihi" },
  { value: "COZUM", label: "Çözüm tarihi" },
  { value: "KAPANIS", label: "Kapanış tarihi" },
  { value: "PLAN", label: "Plan tarihi" },
];

function hazirAraliklar(): { ad: string; aralik: [Dayjs, Dayjs] }[] {
  const bugun = dayjs();
  const pazartesi = bugun.subtract((bugun.day() + 6) % 7, "day");
  const gecenAy = bugun.subtract(1, "month");
  return [
    { ad: "Bugün", aralik: [bugun, bugun] },
    { ad: "Bu hafta", aralik: [pazartesi, bugun] },
    { ad: "Bu ay", aralik: [bugun.startOf("month"), bugun] },
    { ad: "Son 30 gün", aralik: [bugun.subtract(29, "day"), bugun] },
    { ad: "Geçen ay", aralik: [gecenAy.startOf("month"), gecenAy.endOf("month")] },
  ];
}

export default function RaporFiltresi({ deger, degisti, tekrarGun }: RaporFiltresiProps) {
  const { kullanici } = useAuth();
  const tumBirimler = kullanici?.role.scope === "TUMU";
  const birimler = (tumBirimler ? Object.keys(BIRIM_ETIKETLERI) : (kullanici?.birimler ?? [])).map(
    (b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }),
  );
  const guncelle = (ek: Partial<RaporFiltresiDegeri>) => degisti({ ...deger, ...ek });
  const aralik: [Dayjs, Dayjs] | null =
    deger.baslangic && deger.bitis ? [dayjs(deger.baslangic), dayjs(deger.bitis)] : null;

  return (
    <Space wrap size={[8, 8]} style={{ width: "100%" }}>
      <DatePicker.RangePicker
        format="DD.MM.YYYY"
        value={aralik}
        allowClear={false}
        onChange={(d) => {
          if (d?.[0] && d[1]) guncelle({ baslangic: d[0].format(ISO), bitis: d[1].format(ISO) });
        }}
      />
      <Space.Compact>
        {hazirAraliklar().map((h) => (
          <Button
            key={h.ad}
            size="small"
            onClick={() => guncelle({ baslangic: h.aralik[0].format(ISO), bitis: h.aralik[1].format(ISO) })}
          >
            {h.ad}
          </Button>
        ))}
      </Space.Compact>
      <Select
        style={{ minWidth: 150 }}
        value={deger.tarih_esasi ?? "ACILIS"}
        options={TARIH_ESASLARI}
        onChange={(v) => guncelle({ tarih_esasi: v })}
        aria-label="Tarih esası"
      />
      <Select
        mode="multiple"
        allowClear
        style={{ minWidth: 170 }}
        placeholder="Kategori"
        value={deger.kategori ?? []}
        options={KATEGORILER}
        onChange={(v) => guncelle({ kategori: v.length ? v : undefined })}
      />
      <Select
        mode="multiple"
        allowClear
        style={{ minWidth: 170 }}
        placeholder={tumBirimler ? "Birim (tümü)" : "Birimlerim"}
        value={deger.birim ?? []}
        options={birimler}
        onChange={(v) => guncelle({ birim: v.length ? v : undefined })}
      />
      <Select
        mode="multiple"
        allowClear
        style={{ minWidth: 140 }}
        placeholder="Durum grubu"
        value={deger.durum_grubu ?? []}
        options={DURUM_GRUPLARI}
        onChange={(v) => guncelle({ durum_grubu: v.length ? v : undefined })}
      />
      <Select
        mode="multiple"
        allowClear
        style={{ minWidth: 130 }}
        placeholder="Öncelik"
        value={deger.oncelik ?? []}
        options={ONCELIKLER}
        onChange={(v) => guncelle({ oncelik: v.length ? v : undefined })}
      />
      <Input.Search
        allowClear
        style={{ width: 150 }}
        placeholder="Şehir"
        defaultValue={deger.sehir}
        onSearch={(v) => guncelle({ sehir: v.trim() || undefined })}
      />
      {tekrarGun && (
        <InputNumber
          min={7}
          max={180}
          style={{ width: 150 }}
          addonAfter="gün"
          placeholder="Pencere"
          value={deger.tekrar_gun}
          onChange={(v) => guncelle({ tekrar_gun: v ?? undefined })}
        />
      )}
    </Space>
  );
}
