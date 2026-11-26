/**
 * Servis e-posta kutusu (TS-200): bildirim e-postası aç/kapat, özet saati,
 * deneme sınırı ve giden kutusu. 2026-11-18'de Operasyon Merkezi sekmesinden
 * Yönetim'e taşındı (dispeçer ekranında teknik yönetici işi duruyordu).
 * İzin `operasyon.yonet`.
 */
import { EpostaSekmesi } from "./OperasyonMerkeziPage";

export default function EpostaKutusuPage() {
  return (
    <div className="fm-sayfa">
      <EpostaSekmesi />
    </div>
  );
}
