/**
 * Kapanan İşler (2026-11-25, kullanıcı isteği): son onayı verilip kapatılmış
 * işler onay bölümünden ayrıldı; Servis İşleri altında ayrı bölümde, İş Emri
 * Onayı gibi birim sekmeli. Liste `kpi=kapanan_isler` (PB hariç).
 */
import { BirimSekmeliIsler } from "./IsEmriOnayiPage";

export default function KapananIslerPage() {
  return (
    <BirimSekmeliIsler
      yol="/kapanan-isler"
      kpi="kapanan_isler"
      ipucu="kapanan işleri"
      hatirlaAnahtari="kapanan-isler"
      durumSeridi={false}
    />
  );
}
