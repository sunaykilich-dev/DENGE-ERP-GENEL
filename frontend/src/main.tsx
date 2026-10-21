import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, Card, ConfigProvider, Empty } from "antd";
import trTR from "antd/locale/tr_TR";
import dayjs from "dayjs";
import "dayjs/locale/tr";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import AppLayout, { acilisYolu } from "./components/AppLayout";
import BakimPage from "./pages/BakimPage";
import BenimIslerimPage from "./pages/BenimIslerimPage";
import PersonelPage from "./pages/PersonelPage";
import ServisEkipmanPage from "./pages/ServisEkipmanPage";
import ServisIsKartiMobil from "./pages/ServisIsKartiMobil";
import ServisIsleriPage from "./pages/ServisIsleriPage";
import ServisPaneli from "./pages/ServisPaneli";
import ServisPlanlamaPage from "./pages/ServisPlanlamaPage";
import ServisTanimlarPage from "./pages/ServisTanimlarPage";
import AboneliklerPage from "./pages/AboneliklerPage";
import AraclarPage from "./pages/AraclarPage";
import AuditPage from "./pages/AuditPage";
import CihazlarPage from "./pages/CihazlarPage";
import HakEdisPage from "./pages/HakEdisPage";
import HatlarPage from "./pages/HatlarPage";
import IsEmirleriPage from "./pages/IsEmirleriPage";
import KvkkPage from "./pages/KvkkPage";
import PanelPage from "./pages/PanelPage";
import GorevlerPage from "./pages/GorevlerPage";
import RaporlarPage from "./pages/RaporlarPage";
import SiparislerPage from "./pages/SiparislerPage";
import TeklifPublicPage from "./pages/TeklifPublicPage";
import StokPage from "./pages/StokPage";
import TahsilatPage from "./pages/TahsilatPage";
import TekliflerPage from "./pages/TekliflerPage";
import HesaplarPage from "./pages/HesaplarPage";
import IceAktarmaPage from "./pages/IceAktarmaPage";
import LoginPage from "./pages/LoginPage";
import MfaKurulumPage from "./pages/MfaKurulumPage";
import RmaPage from "./pages/RmaPage";
import SatinAlmaPage from "./pages/SatinAlmaPage";
import SettingsPage from "./pages/SettingsPage";
import UrunlerPage from "./pages/UrunlerPage";
import UsersPage from "./pages/UsersPage";
import "./styles.css";
import { theme } from "./theme";

dayjs.locale("tr");

const qc = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

function Yonlendirici() {
  return (
    <Routes>
      {/* Müşterinin teklif bağlantısı OTURUMSUZ açılır; kimlik kapısının
          önünde durur, yoksa müşteri giriş ekranına düşerdi. */}
      <Route path="/teklif/:jeton" element={<TeklifPublicPage />} />
      <Route path="*" element={<KorumaliUygulama />} />
    </Routes>
  );
}

/**
 * Açılış (`/`): Panel yalnız `rapor.gor` sahibine çizilir; diğer kullanıcı
 * izninden türeyen ilk ekrana yönlendirilir (plan §1.10, KD-30). Servis
 * kullanıcısı `/` PanelPage'in 403 yağmurunu görmez.
 */
function Acilis() {
  const { yetkili } = useAuth();
  const hedef = acilisYolu(yetkili);
  if (hedef === "/") return <PanelPage />;
  if (hedef) return <Navigate to={hedef} replace />;
  return (
    <Card>
      <Empty description="Hesabınıza tanımlı bir ekran yok. Yöneticinizden yetki isteyin." />
    </Card>
  );
}

function KorumaliUygulama() {
  const { kullanici, yukleniyor } = useAuth();
  if (yukleniyor) return null;
  if (!kullanici) return <LoginPage />;
  // MFA zorunluysa kurulum bitene kadar uygulamanın hiçbir ekranı çizilmez;
  // backend zaten uçları kapatıyor, burası kullanıcıya çıkışı gösteriyor.
  if (kullanici.mfa_kurulumu_gerekli) return <MfaKurulumPage />;
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Acilis />} />
        <Route path="/gorevler" element={<GorevlerPage />} />
        <Route path="/raporlar" element={<RaporlarPage />} />
        <Route path="/kvkk" element={<KvkkPage />} />
        <Route path="/stok" element={<StokPage />} />
        <Route path="/teklifler" element={<TekliflerPage />} />
        <Route path="/siparisler" element={<SiparislerPage />} />
        <Route path="/abonelikler" element={<AboneliklerPage />} />
        <Route path="/tahsilat" element={<TahsilatPage />} />
        <Route path="/ice-aktarma" element={<IceAktarmaPage />} />
        <Route path="/rma" element={<RmaPage />} />
        <Route path="/satinalma" element={<SatinAlmaPage />} />
        <Route path="/is-emirleri" element={<IsEmirleriPage />} />
        <Route path="/hakedis" element={<HakEdisPage />} />
        <Route path="/cihazlar" element={<CihazlarPage />} />
        <Route path="/cihazlar/:kimlik" element={<CihazlarPage />} />
        <Route path="/hatlar" element={<HatlarPage />} />
        <Route path="/hatlar/:id" element={<HatlarPage />} />
        <Route path="/araclar" element={<AraclarPage />} />
        <Route path="/araclar/:id" element={<AraclarPage />} />
        <Route path="/hesaplar" element={<HesaplarPage />} />
        <Route path="/hesaplar/:id" element={<HesaplarPage />} />
        <Route path="/urunler" element={<UrunlerPage />} />
        <Route path="/urunler/:id" element={<UrunlerPage />} />
        <Route path="/kullanicilar" element={<UsersPage />} />
        <Route path="/ayarlar" element={<SettingsPage />} />
        <Route path="/denetim" element={<AuditPage />} />
        {/* --- Teknik servis (Dalga 0/1, plan §1.10) --- */}
        <Route path="/servis-paneli" element={<ServisPaneli />} />
        <Route path="/servis-isleri" element={<ServisIsleriPage />} />
        <Route path="/servis-isleri/:id" element={<ServisIsleriPage />} />
        <Route path="/servis-planlama" element={<ServisPlanlamaPage />} />
        <Route path="/benim-islerim" element={<BenimIslerimPage />} />
        <Route path="/benim-islerim/:id" element={<ServisIsKartiMobil />} />
        <Route path="/servis-ekipman" element={<ServisEkipmanPage />} />
        <Route path="/servis-ekipman/:id" element={<ServisEkipmanPage />} />
        <Route path="/bakim" element={<BakimPage />} />
        <Route path="/servis-tanimlar" element={<ServisTanimlarPage />} />
        <Route path="/personel" element={<PersonelPage />} />
        <Route path="/personel/:id" element={<PersonelPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider locale={trTR} theme={theme}>
      <AntApp>
        <QueryClientProvider client={qc}>
          <BrowserRouter>
            <AuthProvider>
              <Yonlendirici />
            </AuthProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
