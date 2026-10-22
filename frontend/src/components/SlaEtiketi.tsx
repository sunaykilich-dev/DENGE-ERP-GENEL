import { Tag, Tooltip } from "antd";
import dayjs from "dayjs";

import { SLA_RENKLERI, sureMetni, type SlaBlogu } from "../api/servisOperasyon";

/**
 * SLA etiketi — sunucunun `sla` bloğunu GÖSTERİR, hesaplamaz (TS-081, E10-18).
 *
 * Durum, kalan dakika, hedef ve PB vadesi sunucudaki tek SLA modülünden gelir;
 * burada yalnız metne çevrilir: "Kalan 3 sa 20 dk" / "Gecikti 1 sa" /
 * "Durduruldu" / "Vade: Ekim 2026". Öncelikten saat türetilmez (grep testi).
 * Servis işi detayı, Operasyon Merkezi ve Benim İşlerim aynı bileşeni kullanır.
 */
export interface SlaEtiketiProps {
  sla: SlaBlogu | null | undefined;
  /** Kısa: yalnız etiket (liste satırı); uzun: hedef zamanı da yazılır. */
  kisa?: boolean;
}

function etiketMetni(sla: SlaBlogu): string {
  if (sla.durum === "SLA_DISI_PB") return sla.vade_ay ? `Vade: ${sla.vade_ay}` : sla.ad;
  if (sla.kalan_dk == null) return sla.ad;
  if (sla.durum === "ASILDI") return `Gecikti ${sureMetni(sla.kalan_dk)}`;
  if (sla.durum === "DURDURULDU") return `Durduruldu (kalan ${sureMetni(sla.kalan_dk)})`;
  return `Kalan ${sureMetni(sla.kalan_dk)}`;
}

export default function SlaEtiketi({ sla, kisa = true }: SlaEtiketiProps) {
  if (!sla) return null;
  const metin = etiketMetni(sla);
  const ipucu = [
    `SLA: ${sla.ad}`,
    sla.hedef_at ? `Hedef: ${dayjs(sla.hedef_at).format("DD.MM.YYYY HH:mm")}` : null,
    sla.ilk_hedef_at && sla.ilk_hedef_at !== sla.hedef_at
      ? `İlk hedef: ${dayjs(sla.ilk_hedef_at).format("DD.MM.YYYY HH:mm")}`
      : null,
    sla.durdurulan_dk ? `İş beklemesiyle durdurulan: ${sureMetni(sla.durdurulan_dk)}` : null,
    sla.kaynak === "GECIS" ? "Hedef SLA yürürlük anından damgalandı" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Tooltip title={ipucu}>
      <span style={{ whiteSpace: "nowrap" }}>
        <Tag color={SLA_RENKLERI[sla.durum] ?? "default"} style={{ marginInlineEnd: 0 }}>
          {metin}
        </Tag>
        {!kisa && sla.hedef_at && (
          <span style={{ marginInlineStart: 6, fontSize: 12, color: "var(--ant-color-text-secondary)" }}>
            Hedef {dayjs(sla.hedef_at).format("DD.MM.YYYY HH:mm")}
          </span>
        )}
      </span>
    </Tooltip>
  );
}
