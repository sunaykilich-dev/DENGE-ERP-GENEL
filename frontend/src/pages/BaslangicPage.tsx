/**
 * Başlangıç sayfası (`/`, `/baslangic`) — Fiori launchpad.
 *
 * Eski rol bazlı açılış kuralı (plan §1.10, KD-30) korunur ama artık
 * YÖNLENDİRMEZ: kullanıcının açılış ekranının bulunduğu sekmeye kaydırır
 * (ör. teknisyen → "Teknik Servis Uygulamaları", mobilite → "Mobilite").
 * Mobilite Paneli `/panel` yoluna taşındı ve "Mobilite" grubunda kutucuktur.
 */
import { useAuth } from "../auth/AuthContext";
import Launchpad from "../fiori/Launchpad";
import { acilisGrubu } from "../fiori/uygulamalar";

export default function BaslangicPage() {
  const { yetkili } = useAuth();
  return <Launchpad ilkGrup={acilisGrubu(yetkili)} />;
}
