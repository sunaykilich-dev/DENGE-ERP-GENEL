/**
 * Ortak rota kapısı (rol testi B-06, sızıntı denetimi madde 4).
 *
 * Menüde olmayan bir sayfa URL ile açıldığında sayfa iskeleti, "Veri Yok"
 * tablosu ve arkada 403 yağmuru yerine tek ve açık bir sonuç çizilir:
 *  - Katalogdaki (`uygulamalar.ts`) uygulamanın izni yoksa: "Bu sayfayı görme
 *    yetkiniz yok".
 *  - Ekran yalnız DENGE MOBİLİTE'de açılıyorsa (`yalnizMobilite`) ve etkin şirket
 *    başkaysa ya da sunucu sayfa verisini 403 `SIRKET_DISI` ile reddettiyse:
 *    "Bu sayfa <şirket> şirketinde kullanılamaz — şirket seçiciden değiştirin".
 *    Kullanıcı DENGE MOBİLİTE üyesiyse tek tıkla geçiş düğmesi.
 * İzin kodu burada yazılmaz; katalogdan okunur (tek kaynak). Bu yalnız arayüz
 * kapısıdır, sunucu her uçta kendi kontrolünü yapar.
 */
import { Button, Result } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { SIRKET_DISI_OLAYI } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useSirket } from "../auth/SirketContext";
import { uygulamaYetkili, yoldanUygulama } from "../fiori/uygulamalar";

const MOBILITE = "MOBILITE";

export default function RotaKapisi({ children }: { children: ReactNode }) {
  const { yetkili } = useAuth();
  const { aktif, sirketler, degistir, degisiyor } = useSirket();
  const { pathname } = useLocation();
  // Sunucunun SIRKET_DISI dediği sayfa yolu ve mesajı (yol değişince geçersiz).
  const [reddedilen, setReddedilen] = useState<{ yol: string; mesaj: string } | null>(null);

  useEffect(() => {
    const dinle = (e: Event) =>
      setReddedilen({ yol: window.location.pathname, mesaj: (e as CustomEvent<string>).detail });
    window.addEventListener(SIRKET_DISI_OLAYI, dinle);
    return () => window.removeEventListener(SIRKET_DISI_OLAYI, dinle);
  }, []);

  const uygulama = yoldanUygulama(pathname);

  if (uygulama && !uygulamaYetkili(uygulama, yetkili)) {
    return (
      <Result
        status="403"
        title="Bu sayfayı görme yetkiniz yok"
        subTitle={`"${uygulama.baslik}" ekranı rolünüze açık değil. Gerekirse sistem yöneticinizden yetki isteyin.`}
        extra={
          <Link to="/">
            <Button type="primary">Açılış sayfasına dön</Button>
          </Link>
        }
      />
    );
  }

  const mobiliteDisi = !!uygulama?.yalnizMobilite && !!aktif && aktif.kod !== MOBILITE;
  // Ortak ekranlar (müşteri kartı, teklif…) bir alt sorgusu reddedildi diye
  // bütünüyle kapanmaz; yalnız şirkete bağlı ya da katalogda olmayan sayfa.
  const sunucuReddetti =
    reddedilen?.yol === pathname && (!uygulama || !!uygulama.yalnizMobilite);
  if (mobiliteDisi || sunucuReddetti) {
    const mobiliteUyesi = sirketler.some((s) => s.kod === MOBILITE);
    const mobiliteAdi = sirketler.find((s) => s.kod === MOBILITE)?.ad ?? "DENGE MOBİLİTE";
    return (
      <Result
        status="info"
        title={`Bu sayfa ${aktif?.ad ?? "seçili"} şirketinde kullanılamaz — şirket seçiciden değiştirin`}
        subTitle={
          mobiliteDisi || !reddedilen?.mesaj
            ? `"${uygulama?.baslik ?? "Bu ekran"}" yalnız ${mobiliteAdi} şirketinde kullanılır.`
            : reddedilen.mesaj
        }
        extra={[
          mobiliteUyesi && aktif?.kod !== MOBILITE && (
            <Button key="gec" type="primary" loading={degisiyor} onClick={() => degistir(MOBILITE)}>
              {mobiliteAdi} şirketine geç
            </Button>
          ),
          <Link key="ana" to="/">
            <Button>Açılış sayfasına dön</Button>
          </Link>,
        ]}
      />
    );
  }

  return <>{children}</>;
}
