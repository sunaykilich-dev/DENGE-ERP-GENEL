/**
 * İl seçici — 81 il + "KKTC" + "Yurt dışı" (KARARLAR 2026-11-04 §6.11, B14).
 *
 * Sunucu (`ana_veri.il_dogrula`) ili 81 il listesine göre tek yazıma çevirir;
 * listede olmayan tek kabul edilen değer yurt dışıdır: "Yurt dışı",
 * "Yurt dışı - Nijerya", "KKTC" → "Yurt dışı" / "Yurt dışı (Ülke)". Ülke
 * kataloğu Faz C olduğundan ülke serbest metindir: "Yurt dışı" seçilince
 * yanına ülke yazılır ve değer "Yurt dışı - Ülke" olarak gönderilir.
 * Kayıtlı "Yurt dışı (Ülke)" değeri geri okunurken ülke kutusuna ayrılır.
 */
import { Input, Select, Space } from "antd";

const IL_ADLARI = [
  "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya", "Ankara", "Antalya", "Artvin",
  "Aydın", "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa", "Çanakkale",
  "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
  "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Isparta", "Mersin",
  "İstanbul", "İzmir", "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir", "Kocaeli",
  "Konya", "Kütahya", "Malatya", "Manisa", "Kahramanmaraş", "Mardin", "Muğla", "Muş",
  "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas",
  "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van", "Yozgat",
  "Zonguldak", "Aksaray", "Bayburt", "Karaman", "Kırıkkale", "Batman", "Şırnak", "Bartın",
  "Ardahan", "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye", "Düzce",
];

export const YURT_DISI = "Yurt dışı";
const KKTC = "KKTC";

const SECENEKLER = [
  ...[...IL_ADLARI].sort((a, b) => a.localeCompare(b, "tr")).map((il) => ({ value: il, label: il })),
  { value: KKTC, label: "KKTC (Kuzey Kıbrıs)" },
  { value: YURT_DISI, label: "Yurt dışı (ülke yazılır)" },
];

const kucuk = (s: string) => s.toLocaleLowerCase("tr");

/** "Yurt dışı (Nijerya)" / "Yurt dışı - Nijerya" / "Yurt dışı" → ülke; değilse null. */
function yurtDisiUlkesi(deger: string | undefined): string | null {
  if (!deger) return null;
  const m = /^yurt\s*d[ıi][şs][ıi]\s*(.*)$/i.exec(deger.trim());
  if (!m) return null;
  const kalan = m[1].trim();
  // Sunucunun yazımı "Yurt dışı (Ülke)"; kullanıcının yazımı "Yurt dışı - Ülke"
  // (sondaki boşluk korunur, yoksa iki kelimelik ülke yazılamaz).
  const parantez = /^\((.*)\)$/.exec(kalan);
  return parantez ? parantez[1].trim() : m[1].replace(/^[\s\-/:,]+/, "");
}

export default function IlSecici({
  value,
  onChange,
  disabled,
  placeholder = "İl seçin",
}: {
  value?: string | null;
  onChange?: (v: string | undefined) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const ulke = yurtDisiUlkesi(value ?? undefined);
  const yurtDisi = ulke !== null;
  // "Yurt dışı (KKTC)" kayıtlı değeri seçicide KKTC olarak görünür.
  const kktc = yurtDisi && kucuk(ulke) === "kktc";
  const secili = kktc ? KKTC : yurtDisi ? YURT_DISI : (value ?? undefined);

  return (
    <Space.Compact style={{ width: "100%" }}>
      <Select
        showSearch
        allowClear
        disabled={disabled}
        placeholder={placeholder}
        value={secili || undefined}
        options={SECENEKLER}
        filterOption={(girdi, o) => kucuk(String(o?.label ?? "")).includes(kucuk(girdi))}
        onChange={(v?: string) => onChange?.(v || undefined)}
        style={{ width: yurtDisi && !kktc ? "45%" : "100%" }}
      />
      {yurtDisi && !kktc && (
        <Input
          disabled={disabled}
          placeholder="Ülke (ör. Nijerya)"
          maxLength={60}
          value={ulke}
          onChange={(e) => {
            const u = e.target.value.trim() ? e.target.value : "";
            onChange?.(u ? `${YURT_DISI} - ${u}` : YURT_DISI);
          }}
          style={{ width: "55%" }}
        />
      )}
    </Space.Compact>
  );
}
