/**
 * İş Emri Onayı (2026-11-10, kullanıcı isteği): onaya gelen işler Servis
 * İşleri'nden ayrı bir modülde, birim birim sekmede.
 *
 * - Liste = Ana Panel "Bekleyen Onaylar" kutusunun AYNI süzgeci
 *   (`kpi=onay_bekleyen`: ekip lideri/kalite onayı ya da son onay/kapanış
 *   bekleyen işler, PB hariç). Sayı = liste; yeni sunucu ucu yok.
 * - Sekmeler: Güvenlik, Haberleşme, Mobilite (sonra kullanıcının diğer
 *   birimleri). Yalnız kullanıcının üyesi olduğu şirketlerin birimleri çizilir.
 * - Şirket ayrımı (KARARLAR 2026-11-04 §1) korunur: sunucu yalnız etkin
 *   şirketin işlerini verir. Başka şirketin birimi seçilince etkin şirket ona
 *   geçer ve kullanıcı bu ekranda, o birimin sekmesinde kalır.
 * - Onay düğmeleri (tekli/toplu kalite onayı, son onay) ortak liste ve
 *   ayrıntı ekranındakiyle aynıdır; izinleri sunucuda denetlenir.
 */
import { ApiOutlined, CarOutlined, SafetyOutlined, ToolOutlined } from "@ant-design/icons";
import { useMemo } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useSirket } from "../auth/SirketContext";
import { ServisIsListesi, type KategoriAlani, type ServisKategorisi } from "./ServisIsleriPage";

const YOL = "/is-emri-onayi";
const KPI = "onay_bekleyen";
const ALANLAR: readonly KategoriAlani[] = ["kpi", "birim"];

/** Sekme sırası: kullanıcının istediği üç birim önce, diğerleri sonra. */
const BIRIM_SEKMELERI: { kod: string; ad: string; ikon: React.ReactNode }[] = [
  { kod: "GUVENLIK", ad: "GÜVENLİK", ikon: <SafetyOutlined /> },
  { kod: "HABERLESME", ad: "HABERLEŞME", ikon: <ApiOutlined /> },
  { kod: "MOBILITE", ad: "MOBİLİTE", ikon: <CarOutlined /> },
  { kod: "BARIYER", ad: "SET BARİYER", ikon: <ToolOutlined /> },
  { kod: "POC", ad: "POC", ikon: <ToolOutlined /> },
  { kod: "ARAC_TAKIP", ad: "ARAÇ TAKİP", ikon: <ToolOutlined /> },
];

export default function IsEmriOnayiPage() {
  const git = useNavigate();
  const { id } = useParams();
  const [arama] = useSearchParams();
  const { sirketler, aktif, menuBirimleri, degistir, destekleniyor } = useSirket();

  // Birim → şirket (yalnız üyesi olunan şirketler listelenir).
  const birimSirketi = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of sirketler) for (const b of s.birimler) m.set(b, s.kod);
    return m;
  }, [sirketler]);

  const kategoriler = useMemo<ServisKategorisi[]>(
    () =>
      BIRIM_SEKMELERI.filter((b) => {
        if (!destekleniyor) return true; // şirket ucu yok: süzgeçsiz
        const sirket = birimSirketi.get(b.kod);
        if (!sirket) return false;
        // Etkin şirkette kullanıcının kapsamı biliniyor; diğerlerinde şirket üyeliği yeter.
        return sirket !== aktif?.kod || !menuBirimleri || menuBirimleri.has(b.kod);
      }).map((b) => ({
        kod: b.kod,
        ad: b.ad,
        renk: birimSirketi.get(b.kod) === aktif?.kod || !destekleniyor ? "mavi" : "yesil",
        ikon: b.ikon,
        ipucu:
          birimSirketi.get(b.kod) && birimSirketi.get(b.kod) !== aktif?.kod
            ? `${sirketler.find((s) => s.kod === birimSirketi.get(b.kod))?.ad ?? ""} şirketine geçer`
            : `${b.ad} onay bekleyen işleri`,
        suzgec: { kpi: KPI, birim: b.kod },
      })),
    [destekleniyor, birimSirketi, aktif?.kod, menuBirimleri, sirketler],
  );

  // Varsayılan sekme: etkin şirketin ilk birimi.
  const varsayilan =
    kategoriler.find((k) => !destekleniyor || birimSirketi.get(k.kod) === aktif?.kod)?.kod ??
    kategoriler[0]?.kod;

  const kategoriSecimi = (kod: string) => {
    const sirket = birimSirketi.get(kod);
    if (!destekleniyor || !sirket || sirket === aktif?.kod) return false;
    degistir(sirket, `${YOL}?kpi=${KPI}&birim=${kod}`);
    return true;
  };

  const yolEki = arama.toString() ? `?${arama.toString()}` : "";
  return (
    <ServisIsListesi
      kategoriler={kategoriler}
      kategoriAlanlari={ALANLAR}
      kategoriSecimi={kategoriSecimi}
      varsayilanKategori={varsayilan}
      yeniKayit={false}
      hatirlaAnahtari="is-emri-onayi"
      detayId={id ? Number(id) : null}
      detayAc={(x) => git(x ? `${YOL}/${x}${yolEki}` : `${YOL}${yolEki}`)}
    />
  );
}
