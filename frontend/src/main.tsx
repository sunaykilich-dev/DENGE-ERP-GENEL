import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import trTR from "antd/locale/tr_TR";
import dayjs from "dayjs";
import "dayjs/locale/tr";
import { StrictMode, Suspense, lazy, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { useSirket } from "./auth/SirketContext";
import { MENU_AGACI, acilisYolu, gorunurMenu } from "./fiori/menu";
import AppLayout from "./components/AppLayout";
import AtolyePage from "./pages/AtolyePage";
import BakimPage from "./pages/BakimPage";
import BenimIslerimPage from "./pages/BenimIslerimPage";
import EgitimPage from "./pages/EgitimPage";
import BelgelerimPage from "./pages/BelgelerimPage";
import GelisimKartimPage from "./pages/GelisimKartimPage";
import IkBelgelerPage from "./pages/IkBelgelerPage";
import KiralamalarPage from "./pages/KiralamalarPage";
import KiralikEnvanterPage from "./pages/KiralikEnvanterPage";
import OperasyonMerkeziPage from "./pages/OperasyonMerkeziPage";
import EpostaKutusuPage from "./pages/EpostaKutusuPage";
import PersonelPage from "./pages/PersonelPage";
import ServisAnaVeriPage from "./pages/ServisAnaVeriPage";
import ServisMaliyetPage from "./pages/ServisMaliyetPage";
import YedekParcaPage from "./pages/YedekParcaPage";
import ServisEkipmanPage from "./pages/ServisEkipmanPage";
import ServisIsKartiMobil from "./pages/ServisIsKartiMobil";
import IsEmriOnayiPage from "./pages/IsEmriOnayiPage";
import ServisIsleriPage from "./pages/ServisIsleriPage";
import ServisPlanlamaPage from "./pages/ServisPlanlamaPage";
import ServisRaporlariPage from "./pages/ServisRaporlariPage";
import ServisTanimlarPage from "./pages/ServisTanimlarPage";
import ZamanTakibiPage from "./pages/ZamanTakibiPage";
import FaturaDevriPage from "./pages/FaturaDevriPage";
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
import TekliflerimPage from "./pages/TekliflerimPage";
import SatislarimPage from "./pages/SatislarimPage";
import HesaplarPage from "./pages/HesaplarPage";
import IceAktarmaPage from "./pages/IceAktarmaPage";
import LoginPage from "./pages/LoginPage";
import MfaKurulumPage from "./pages/MfaKurulumPage";
import ParolaDegistirPage from "./pages/ParolaDegistirPage";
import RmaPage from "./pages/RmaPage";
import SatinAlmaPage from "./pages/SatinAlmaPage";
import SettingsPage from "./pages/SettingsPage";
import UrunlerPage from "./pages/UrunlerPage";
import UsersPage from "./pages/UsersPage";
import "./styles.css";
import { theme } from "./theme";

dayjs.locale("tr");

// Ana Panel ayrı pakette yazılıyor (KARARLAR 2026-11-04 §4); tembel yüklenir.
const AnaPanelPage = lazy(() => import("./pages/AnaPanelPage"));

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
 * Mobilite Paneli (`/panel`) yalnız `rapor.gor` sahibine çizilir; izni
 * olmayan launchpad'e döner — servis kullanıcısı PanelPage'in 403 yağmurunu
 * görmez (plan §1.10, KD-30).
 */
function PanelKapisi() {
  const { yetkili } = useAuth();
  if (!yetkili("rapor.gor")) return <Navigate to="/" replace />;
  return <PanelPage />;
}

/**
 * Açılış (`/`, `/baslangic`; rol testi B-01): servis çalışanına Ana Panel,
 * diğer rollere kendi ana ekranı (satış → Teklifler, finans → Fatura Devri…;
 * bkz. `acilisYolu`). Kabuk bunu şirket bilgisi
 * yüklendikten sonra çizer; menüyle aynı süzgeç kullanılır.
 */
function Acilis() {
  const { yetkili } = useAuth();
  const { menuBirimleri } = useSirket();
  const hedef = useMemo(
    () => acilisYolu(gorunurMenu(MENU_AGACI, { yetkili, aktifBirimler: menuBirimleri }), yetkili),
    [yetkili, menuBirimleri],
  );
  return <Navigate to={hedef} replace />;
}

function AnaPanel() {
  return (
    <Suspense fallback={null}>
      <AnaPanelPage />
    </Suspense>
  );
}

function KorumaliUygulama() {
  const { kullanici, yukleniyor } = useAuth();
  if (yukleniyor) return null;
  if (!kullanici) return <LoginPage />;
  // MFA zorunluysa kurulum bitene kadar uygulamanın hiçbir ekranı çizilmez;
  // backend zaten uçları kapatıyor, burası kullanıcıya çıkışı gösteriyor.
  if (kullanici.mfa_kurulumu_gerekli) return <MfaKurulumPage />;
  // Geçici/ilk kurulum parolası (TS-212): sunucu diğer uçları 403
  // PAROLA_DEGISMELI ile kapatıyor; kullanıcı değiştirene kadar uygulama çizilmez.
  if (kullanici.parola_degismeli) return <ParolaDegistirPage />;
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* KARARLAR 2026-11-04 §2/§4: açılış Ana Panel (izni olana; yoksa
            rolün ana ekranı — B-01). Kutucuk ekranı (launchpad) ve Servis
            Paneli 2026-11-18'de kaldırıldı; eski yer imleri yönlenir. */}
        <Route path="/" element={<Acilis />} />
        <Route path="/ana-panel" element={<AnaPanel />} />
        <Route path="/baslangic" element={<Acilis />} />
        <Route path="/uygulamalar" element={<Navigate to="/" replace />} />
        <Route path="/panel" element={<PanelKapisi />} />
        <Route path="/gorevler" element={<GorevlerPage />} />
        <Route path="/raporlar" element={<RaporlarPage />} />
        <Route path="/kvkk" element={<KvkkPage />} />
        <Route path="/stok" element={<StokPage />} />
        <Route path="/teklifler" element={<TekliflerPage />} />
        <Route path="/tekliflerim" element={<TekliflerimPage />} />
        <Route path="/satislarim" element={<SatislarimPage />} />
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
        <Route path="/eposta-kutusu" element={<EpostaKutusuPage />} />
        {/* --- Teknik servis (Dalga 0/1, plan §1.10) --- */}
        <Route path="/servis-paneli" element={<Navigate to="/ana-panel" replace />} />
        <Route path="/servis-isleri" element={<ServisIsleriPage />} />
        <Route path="/servis-isleri/:id" element={<ServisIsleriPage />} />
        <Route path="/is-emri-onayi" element={<IsEmriOnayiPage />} />
        <Route path="/is-emri-onayi/:id" element={<IsEmriOnayiPage />} />
        <Route path="/servis-planlama" element={<ServisPlanlamaPage />} />
        <Route path="/benim-islerim" element={<BenimIslerimPage />} />
        <Route path="/benim-islerim/:id" element={<ServisIsKartiMobil />} />
        <Route path="/servis-ekipman" element={<ServisEkipmanPage />} />
        <Route path="/servis-ekipman/:id" element={<ServisEkipmanPage />} />
        <Route path="/bakim" element={<BakimPage />} />
        <Route path="/servis-tanimlar" element={<ServisTanimlarPage />} />
        <Route path="/personel" element={<PersonelPage />} />
        <Route path="/personel/:id" element={<PersonelPage />} />
        {/* --- Teknik servis (Dalga 2, plan §1.10) --- */}
        <Route path="/operasyon" element={<OperasyonMerkeziPage />} />
        <Route path="/atolye" element={<AtolyePage />} />
        <Route path="/atolye/:id" element={<AtolyePage />} />
        <Route path="/kiralamalar" element={<KiralamalarPage />} />
        <Route path="/kiralamalar/:id" element={<KiralamalarPage />} />
        <Route path="/kiralik-envanter" element={<KiralikEnvanterPage />} />
        <Route path="/yedek-parca" element={<YedekParcaPage />} />
        <Route path="/servis-maliyet" element={<ServisMaliyetPage />} />
        <Route path="/servis-ana-veri" element={<ServisAnaVeriPage />} />
        <Route path="/egitim" element={<EgitimPage />} />
        <Route path="/egitim/:id" element={<EgitimPage />} />
        <Route path="/gelisim-kartim" element={<GelisimKartimPage />} />
        <Route path="/ik-belgeler" element={<IkBelgelerPage />} />
        <Route path="/belgelerim" element={<BelgelerimPage />} />
        {/* --- Teknik servis (Dalga 3, D3-S) --- */}
        <Route path="/servis-raporlari" element={<ServisRaporlariPage />} />
        <Route path="/zaman-takibi" element={<ZamanTakibiPage />} />
        <Route path="/fatura-devri" element={<FaturaDevriPage />} />
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
