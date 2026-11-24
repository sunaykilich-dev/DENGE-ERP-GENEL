/**
 * Servis İşi Formu — açılış/düzenleme formu (TS-033/034).
 *
 * - Müşteri → lokasyon seçimi `MusteriLokasyonSecici` ile SUNUCUDA aranır
 *   (300 ms gecikmeli); seçilen lokasyonun birincil irtibatı forma önerilir,
 *   kullanıcı değiştirebilir. Kart IBAN/VKN göstermez. Hızlı müşteri ekleme
 *   `hesap.kart_yaz|hesap.yaz` olana görünür (KARARLAR 2026-11-04 §6.5;
 *   seçicinin kendi kuralı), diğerlerine "Müşteri İlişkileri'nden kart isteyin" notu.
 * - Yalnız `servis.kurulum_ac` olan (satış destek, `servis.yaz` yok) yalnız
 *   KURULUM türü seçer; sunucu diğer türü 403 ile reddeder (§6.5).
 * - "Geçmiş kayıt (geçiş)" yalnız `servis.gecis_kaydi` olana (TS müdürü)
 *   görünür: seçilince bildirim anındaki 7 gün sınırı kalkar, gerekçe (≥10
 *   karakter) zorunlu; iş SLA dışı (GECIS) doğar (§6.11).
 * - "Aynı lokasyonda açık iş" uyarısı tek kayıttır (`adet` + `isler`, §6.10).
 * - Seri girildikçe açık işte aynı seri sorulur (yalnız uyarı); kayıtta
 *   sunucu 409 `MUKERRER` dönerse kullanıcı listeyi görüp "yine de aç" der.
 * - "Telefonla/uzaktan çözüldü" (`servis.uzaktan_coz`): açılış + sonuç tek
 *   istekte (iş TAMAMLANDI doğar; şef ayrıca kapatır).
 * - Düzenlemede `version` gönderilir (iyimser kilit): başkası değiştirdiyse
 *   409 → çağıran kaydı yeniler. Kapalı işte düzeltme gerekçe ister.
 * - Faz A: yeni işte talep eden kişinin adı ve telefonu ve arıza tanımı
 *   zorunlu (M1.2; lokasyon 2026-11-24'ten beri isteğe bağlı — elden/kargo
 *   gelen cihaz). M1.6 "günlük serviste tek cihaz" 2026-11-24'te kalktı: her
 *   türde birden çok cihaz (PB hariç); her cihazın durumu, onarım bilgisi,
 *   müşteri şikâyeti ve notu (son ikisi yalnız personel) ayrı girilir.
 * - 2026-11-23: seri alanı el okuyucu + kamera düğmeli `SeriOkutucu`. Cihazlı
 *   işte (ayar açıkken) seri zorunlu; okutulmayan (elle yazılan, kütükten
 *   seçilen) seri için neden sorulur. Her serinin kaynağı `seri_okumalari`'yla gider.
 * - 2026-11-24: `servis.planla` olan açarken personel tayin edebilir (isteğe
 *   bağlı); tayin işle tek istekte gider, sunucu tayin kurallarını uygular.
 */
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Divider,
  Form,
  Input,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { personelApi } from "../api/personel";
import {
  HABERLESME_NITELIKLERI,
  nitelikSorulur,
  ONCELIK_ADLARI,
  teknikServisApi,
  type AcilisUyarisi,
  type AtamaSatiri,
  type CihazBilgisi,
  type FormVerileri,
  type IsDetayi,
  type IsGirdisi,
  type MukerrerSonucu,
} from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import MusteriLokasyonSecici, {
  type MusteriLokasyonSecimi,
  type SahaOnerisi,
} from "../components/MusteriLokasyonSecici";
import { CihazBilgisiAlanlari } from "../components/CihazBilgileri";
import SeriOkutucu, { seriAnahtari } from "../components/SeriOkutucu";
import { ELLE_GEREKCELERI, type ElleGerekce, type SeriOkumasi } from "../components/barkod/elleGerekce";
import type { OkumaKaynagi } from "../components/barkod/okuyucuAlgilama";

interface FormDegeri {
  birim: string;
  tur: string;
  oncelik: string;
  talep_kanali: string;
  reported_at: Dayjs | null;
  musteri: MusteriLokasyonSecimi;
  iletisim_ad?: string;
  iletisim_telefon?: string;
  konu: string;
  aciklama?: string;
  seriler: string[];
  proje?: string;
  sistem?: string;
  /** Haberleşme saha işinin niteliği (çoktan seçmeli, zorunlu). */
  nitelikler?: string[];
  uzaktan: boolean;
  cozum_kanali?: "TELEFON" | "UZAKTAN";
  yapilan_islem?: string;
  ariza_nedeni_id?: number;
  gerekce?: string;
  /** Yalnız düzenlemede ve `servis.kapat` ile (E01-16; gerekçe zorunlu). */
  kategori?: string;
  /** Geçiş/içe aktarma kaydı (`servis.gecis_kaydi`): 7 gün sınırı yok, SLA ölçülmez. */
  gecis_kaydi?: boolean;
  gecis_gerekcesi?: string;
  /** Okutulmayan seri(ler) için neden (cihazlı işte zorunlu). */
  elle_gerekce?: ElleGerekce;
  elle_aciklama?: string;
  /** Cihaz başına bilgi; anahtar `seriAnahtari(seri)`. */
  cihaz_bilgileri?: Record<string, CihazBilgisi>;
  /** Açılışta tayin (yalnız `servis.planla`): personel + sorumlu. */
  tayin_kisiler?: number[];
  tayin_sorumlu?: number;
}

const GECIS_GEREKCE_ALT = 10;
const KURULUM = "KURULUM";

const KAPALI = ["TAMAMLANDI", "KAPATILDI", "IPTAL"];

/** Kişiyi listeleyen mükerrer satırı (yalnız kullanıcının görebildiği işler). */
function MukerrerUyarisi({ m }: { m: MukerrerSonucu | null }) {
  if (!m || (!m.mukerrer.length && !m.kapsam_disi_var && !m.ayni_lokasyon.length)) return null;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={4}>
      {(m.mukerrer.length > 0 || m.kapsam_disi_var) && (
        <Alert
          type="warning"
          showIcon
          message="Aynı seri numarasıyla açık servis işi var"
          description={
            m.mukerrer.length
              ? m.mukerrer.map((x) => x.so_no).join(", ")
              : "Başka birimde açık kayıt var (numarası gösterilmez)."
          }
        />
      )}
      {m.ayni_lokasyon.length > 0 && (
        <Alert
          type="info"
          showIcon
          message={`Bu lokasyonda ${m.ayni_lokasyon.length} açık iş var`}
          description={
            <Space size={[8, 0]} wrap>
              {m.ayni_lokasyon.map((x) => (
                <Link key={x.id} to={`/servis-isleri/${x.id}`} target="_blank" rel="noopener">
                  {x.so_no}
                </Link>
              ))}
            </Space>
          }
        />
      )}
    </Space>
  );
}

const KUTUK_TIP_ADI: Record<string, string> = {
  XRAY: "X-Ray",
  KAPI_DEDEKTORU: "Kapı dedektörü",
  EL_DEDEKTORU: "El dedektörü",
  DIGER_GUVENLIK: "Güvenlik cihazı",
  ROLE_TEKRARLAYICI: "Röle",
  TELSIZ: "Telsiz",
  TELSIZ_DIGER: "Telsiz (diğer)",
};

export default function ServisIsFormu({
  is: mevcut,
  formVerileri,
  onKaydedildi,
  onVazgec,
  onCakisma,
  varsayilan,
}: {
  /** Verilirse düzenleme; yoksa yeni iş. */
  is?: IsDetayi | null;
  /**
   * Yeni işte önerilen birim/tür (liste hangi süzgeçle açıksa, ör. Güvenlik ›
   * Kurulum). Kullanıcının seçebileceği değer değilse yok sayılır.
   */
  varsayilan?: { birim?: string; tur?: string };
  formVerileri?: FormVerileri;
  onKaydedildi: (d: IsDetayi) => void;
  onVazgec: () => void;
  /** 409 (başkası değiştirdi): çağıran kaydı yeniden yükler. */
  onCakisma?: () => void;
}) {
  const { message, modal, notification } = App.useApp();
  const navigate = useNavigate();
  const { kullanici, yetkili } = useAuth();
  const [form] = Form.useForm<FormDegeri>();
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const [mukerrer, setMukerrer] = useState<MukerrerSonucu | null>(null);
  const [onerilenIrtibat, setOnerilenIrtibat] = useState<SahaOnerisi["irtibat"]>(null);
  const [irtibatlar, setIrtibatlar] = useState<NonNullable<SahaOnerisi["irtibatlar"]>>([]);
  /** Bu formda eklenen serilerin kaynağı (anahtar `seriAnahtari`). */
  const [kaynaklar, setKaynaklar] = useState<Record<string, OkumaKaynagi>>({});
  const duzenleme = !!mevcut;
  const kapali = !!mevcut && KAPALI.includes(mevcut.status);
  const musteriDuzeltebilir = !duzenleme || (yetkili("servis.planla") && mevcut?.tur !== "PB");
  const uzaktanYetkili = yetkili("servis.uzaktan_coz");
  const kategoriDuzeltebilir = duzenleme && yetkili("servis.kapat") && mevcut?.tur !== "PB";
  // Yalnız kurulum açan (satış destek): `servis.kurulum_ac` var, `servis.yaz` yok.
  const yalnizKurulum = !duzenleme && !yetkili("servis.yaz") && yetkili("servis.kurulum_ac");
  const gecisYetkili = !duzenleme && yetkili("servis.gecis_kaydi");
  const tayinYetkili = !duzenleme && yetkili("servis.planla");

  const birim = Form.useWatch("birim", form);
  const uzaktan = Form.useWatch("uzaktan", form);
  const seriler = Form.useWatch("seriler", form);
  const musteri = Form.useWatch("musteri", form);
  const kategoriDegeri = Form.useWatch("kategori", form);
  const turDegeri = Form.useWatch("tur", form);
  const gecis = !!Form.useWatch("gecis_kaydi", form) && gecisYetkili;
  const nitelikVar = nitelikSorulur(birim, turDegeri);
  // 2026-11-24: tek cihaz yalnız planlı bakımda (1 cihaz = 1 iş).
  const tekCihaz = turDegeri === "PB";
  const elleGerekce = Form.useWatch("elle_gerekce", form);
  const tayinKisiler = Form.useWatch("tayin_kisiler", form);
  const tayinAdaylari = useQuery({
    queryKey: ["atanabilir", birim],
    queryFn: () => personelApi.atanabilir(birim),
    enabled: tayinYetkili && !!birim,
  });
  // Cihazlı işte (ayar açıkken) seri okutulur; elle girilene neden sorulur.
  const okutmaZorunlu =
    !!formVerileri?.seri_okutma?.zorunlu &&
    !!turDegeri &&
    formVerileri.seri_okutma.cihazli_turler.includes(turDegeri) &&
    !gecis;
  const mevcutAnahtarlar = useMemo(
    () => new Set((mevcut?.seriler ?? []).map((s) => seriAnahtari(s.seri_no))),
    [mevcut],
  );
  const kaynakBul = (s: string): OkumaKaynagi | null =>
    mevcutAnahtarlar.has(seriAnahtari(s)) ? null : (kaynaklar[seriAnahtari(s)] ?? "ELLE");
  const elleSeriVar = (seriler ?? []).some((s) => kaynakBul(s) === "ELLE");
  const seriEtiketleri = Object.fromEntries([
    ...(mevcut?.seriler ?? []).map((s) => [seriAnahtari(s.seri_no), s.okuma_etiketi ?? "eski kayıt"]),
    ...(seriler ?? [])
      .filter((s) => !mevcutAnahtarlar.has(seriAnahtari(s)))
      .map((s) => [seriAnahtari(s), kaynakBul(s) === "OKUTMA" ? "Okutuldu" : "Elle"]),
  ]);

  // KARARLAR §12: arıza işinde müşterinin kütükteki cihazı seçilince seri (ve
  // Haberleşmede kayıtlı frekans) kütükten gelir.
  const kutukBirimi = birim === "GUVENLIK" || birim === "HABERLESME";
  const kutukCihazlari = useQuery({
    queryKey: ["kutuk-cihazlari", birim, musteri?.musteriId, musteri?.lokasyonId],
    queryFn: () => teknikServisApi.kutukCihazlari(birim, musteri!.musteriId!, musteri?.lokasyonId),
    enabled: kutukBirimi && !!musteri?.musteriId && mevcut?.tur !== "PB" && turDegeri !== "PB",
  });
  const seciliKutuk = (kutukCihazlari.data ?? []).find(
    (c) => c.serial_no && (seriler ?? []).some((x) => x.trim().toUpperCase() === c.serial_no!.toUpperCase()),
  );

  const arizaNedenleri = useQuery({
    queryKey: ["ariza-nedenleri", birim],
    queryFn: () => teknikServisApi.arizaNedenleri(birim),
    enabled: !!birim && !!uzaktan,
  });

  const onerilenBirim = varsayilan?.birim;
  const onerilenTur = varsayilan?.tur;
  const baslangic = useMemo<Partial<FormDegeri>>(() => {
    if (mevcut) {
      return {
        birim: mevcut.birim,
        tur: mevcut.tur,
        oncelik: mevcut.oncelik,
        talep_kanali: mevcut.talep_kanali ?? undefined,
        reported_at: mevcut.reported_at ? dayjs(mevcut.reported_at) : null,
        musteri: {
          musteriId: mevcut.customer_id,
          musteriAdi: mevcut.musteri?.title ?? null,
          lokasyonId: mevcut.address_id,
        },
        iletisim_ad: mevcut.iletisim_ad ?? undefined,
        iletisim_telefon: mevcut.iletisim_telefon ?? undefined,
        konu: mevcut.konu,
        aciklama: mevcut.aciklama ?? undefined,
        seriler: mevcut.seriler.map((s) => s.seri_no),
        proje: mevcut.proje ?? undefined,
        sistem: mevcut.sistem ?? undefined,
        nitelikler: mevcut.nitelikler ?? undefined,
        uzaktan: false,
        kategori: mevcut.kategori,
      };
    }
    const birimler = formVerileri?.birimler ?? [];
    const varsayilanBirim =
      birimler.find((b) => b.kod === onerilenBirim)?.kod ??
      birimler.find((b) => b.kod === kullanici?.birincil_birim)?.kod ??
      (birimler.length === 1 ? birimler[0].kod : undefined);
    const varsayilanTur = yalnizKurulum
      ? KURULUM
      : onerilenTur && onerilenTur !== "PB"
        ? formVerileri?.turler.find((t) => t.kod === onerilenTur)?.kod
        : undefined;
    return {
      birim: varsayilanBirim,
      ...(varsayilanTur ? { tur: varsayilanTur } : {}),
      oncelik: "NORMAL",
      talep_kanali: "TELEFON",
      reported_at: dayjs(),
      musteri: { musteriId: null, lokasyonId: null },
      seriler: [],
      uzaktan: false,
    };
  }, [mevcut, formVerileri, kullanici, onerilenBirim, onerilenTur, yalnizKurulum]);

  // Rol testi B11: yeni işte sözlük (`form-verileri`) gelmeden form çizilmez;
  // yoksa ilk anda birim/tür boş, talep kanalı ham kod görünüyordu.
  const sozlukBekleniyor = !mevcut && !formVerileri;

  useEffect(() => {
    if (sozlukBekleniyor) return;
    form.resetFields();
    form.setFieldsValue(baslangic);
    setKaynaklar({});
  }, [baslangic, form, sozlukBekleniyor]);

  // Canlı mükerrer uyarısı (yalnız uyarı; asıl kontrol kayıtta sunucuda).
  useEffect(() => {
    const seri = (seriler ?? []).map((s) => s.trim()).filter(Boolean);
    const t = setTimeout(() => {
      if (!seri.length && !musteri?.musteriId) {
        setMukerrer(null);
        return;
      }
      teknikServisApi
        .mukerrerKontrol({
          seri,
          musteri_id: musteri?.musteriId ?? undefined,
          adres_id: musteri?.lokasyonId ?? undefined,
          haric_id: mevcut?.id,
        })
        .then(setMukerrer)
        .catch(() => setMukerrer(null));
    }, 400);
    return () => clearTimeout(t);
  }, [seriler, musteri?.musteriId, musteri?.lokasyonId, mevcut?.id]);

  /** Lokasyon irtibat listesinden seçim: ad/telefon dolar, kayıtta `contact_id` gider. */
  const irtibatSec = (id: number) => {
    const k = irtibatlar.find((x) => x.id === id);
    if (!k) return;
    setOnerilenIrtibat({ id: k.id, ad: k.ad, telefon: k.telefon });
    form.setFieldsValue({
      iletisim_ad: k.ad,
      iletisim_telefon: k.telefon && !k.telefon.includes("*") ? k.telefon : undefined,
    });
  };

  /** Lokasyonun birincil irtibatı önerilir; kullanıcı yazdıysa ezilmez. */
  const sahaOnerisi = (o: SahaOnerisi | null) => {
    setOnerilenIrtibat(o?.irtibat ?? null);
    setIrtibatlar(o?.irtibatlar ?? []);
    if (!o?.irtibat) return;
    const v = form.getFieldsValue(["iletisim_ad", "iletisim_telefon"]);
    if (!v.iletisim_ad && !v.iletisim_telefon) {
      form.setFieldsValue({
        iletisim_ad: o.irtibat.ad,
        iletisim_telefon: o.irtibat.telefon && !o.irtibat.telefon.includes("*") ? o.irtibat.telefon : undefined,
      });
    }
  };

  /** Seriler → kaynağı bilinenler `seri_okumalari`, diğerleri düz `seriler`. */
  function seriAyir(v: FormDegeri) {
    const tum = (v.seriler ?? []).map((s) => s.trim()).filter(Boolean);
    const duz: string[] = [];
    const okumalar: SeriOkumasi[] = [];
    for (const s of tum) {
      const k = kaynakBul(s);
      if (k === "OKUTMA") okumalar.push({ seri_no: s, okuma_kaynagi: "OKUTMA" });
      else if (k === "ELLE" && v.elle_gerekce)
        okumalar.push({
          seri_no: s,
          okuma_kaynagi: "ELLE",
          elle_gerekce: v.elle_gerekce,
          elle_aciklama: v.elle_aciklama?.trim() || null,
        });
      else duz.push(s);
    }
    return { tum, duz, okumalar };
  }

  /** Doldurulmuş cihaz bilgileri (boş alanlı cihaz gönderilmez). */
  function cihazBilgileriKur(v: FormDegeri): (CihazBilgisi & { seri_no: string })[] {
    if (duzenleme) return [];
    const tum = (v.seriler ?? []).map((x) => x.trim()).filter(Boolean);
    return tum.flatMap((seri) => {
      const b = v.cihaz_bilgileri?.[seriAnahtari(seri)];
      if (!b) return [];
      const temiz = Object.fromEntries(
        Object.entries(b).filter(([, d]) => (typeof d === "string" ? d.trim() !== "" : d != null)),
      ) as CihazBilgisi;
      return Object.keys(temiz).length ? [{ seri_no: seri, ...temiz }] : [];
    });
  }

  /** Tayin satırları: tek kişi seçildiyse sorumlu odur; rol saha rolünden. */
  function tayinSatirlari(kisiler: number[], sorumlu?: number): AtamaSatiri[] {
    const lider = sorumlu ?? (kisiler.length === 1 ? kisiler[0] : undefined);
    return kisiler.map((id) => ({
      user_id: id,
      rol: tayinAdaylari.data?.find((k) => k.id === id)?.saha_rolu === "SEF" ? "SEF" : "TEKNISYEN",
      is_lead: id === lider,
    }));
  }

  function govdeKur(v: FormDegeri): IsGirdisi {
    const { duz, okumalar } = seriAyir(v);
    const irtibatAyni =
      !!onerilenIrtibat && (v.iletisim_ad ?? "").trim() === onerilenIrtibat.ad.trim();
    return {
      birim: v.birim,
      tur: v.tur,
      konu: v.konu.trim(),
      customer_id: v.musteri.musteriId as number,
      address_id: v.musteri.lokasyonId ?? null,
      contact_id: irtibatAyni ? onerilenIrtibat?.id : null,
      oncelik: v.oncelik,
      talep_kanali: v.talep_kanali,
      reported_at: v.reported_at ? v.reported_at.toISOString() : null,
      iletisim_ad: v.iletisim_ad?.trim() || null,
      iletisim_telefon: v.iletisim_telefon?.trim() || null,
      proje: v.proje?.trim() || null,
      sistem: v.sistem?.trim() || null,
      aciklama: v.aciklama?.trim() || null,
      seriler: duz,
      ...(cihazBilgileriKur(v).length ? { cihaz_bilgileri: cihazBilgileriKur(v) } : {}),
      ...(okumalar.length ? { seri_okumalari: okumalar } : {}),
      ...(nitelikSorulur(v.birim, v.tur) ? { nitelikler: v.nitelikler ?? [] } : {}),
      ...(tayinYetkili && !v.uzaktan && v.tayin_kisiler?.length
        ? { atamalar: tayinSatirlari(v.tayin_kisiler, v.tayin_sorumlu) }
        : {}),
      ...(gecisYetkili && v.gecis_kaydi
        ? { gecis_kaydi: true, gecis_gerekcesi: (v.gecis_gerekcesi ?? "").trim() }
        : {}),
    };
  }

  /** "Aynı lokasyonda açık iş" (tek uyarı: `adet` + `isler`; eski biçimde yalnız ilk iş). */
  function ayniLokasyonBildir(u: AcilisUyarisi) {
    const isler = u.isler?.length ? u.isler : [{ id: u.id, so_no: u.so_no }];
    const adet = u.adet ?? isler.length;
    notification.info({
      message: `Bu lokasyonda ${adet} açık iş var`,
      description: (
        <Space size={[8, 0]} wrap>
          {isler.map((x) => (
            <a
              key={x.id}
              href={`/servis-isleri/${x.id}`}
              onClick={(e) => {
                e.preventDefault();
                navigate(`/servis-isleri/${x.id}`);
              }}
            >
              {x.so_no}
            </a>
          ))}
        </Space>
      ),
      duration: 10,
    });
  }

  async function yeniKaydet(v: FormDegeri, mukerrerGec = false) {
    const govde = { ...govdeKur(v), mukerrer_gec: mukerrerGec };
    try {
      const sonuc =
        v.uzaktan && uzaktanYetkili
          ? await teknikServisApi.uzaktanCozuldu({
              ...govde,
              cozum_kanali: v.cozum_kanali ?? "TELEFON",
              yapilan_islem: (v.yapilan_islem ?? "").trim(),
              ariza_nedeni_id: v.ariza_nedeni_id ?? null,
            })
          : await teknikServisApi.ac(govde);
      message.success(`${sonuc.so_no} açıldı`);
      for (const u of sonuc.uyarilar ?? []) {
        if (u.kod === "AYNI_LOKASYON") ayniLokasyonBildir(u);
      }
      const yetkinlik = (sonuc.uyarilar ?? []).filter((u) => u.kod === "YETKINLIK");
      if (yetkinlik.length) {
        notification.warning({
          message: "Tayin edildi; yetkinlik uyarısı var",
          description: yetkinlik.map((u) => u.mesaj).join(" · "),
          duration: 10,
        });
      }
      onKaydedildi(sonuc);
    } catch (e) {
      const detay = (e instanceof ApiError ? (e.govde as { detail?: unknown })?.detail : null) as
        | { kod?: string; mesaj?: string; mevcut_isler?: { so_no: string }[] }
        | null;
      if (e instanceof ApiError && e.status === 409 && detay?.kod === "MUKERRER") {
        modal.confirm({
          title: "Mükerrer kayıt olabilir",
          content: (
            <Space orientation="vertical">
              <span>{detay.mesaj}</span>
              <Typography.Text type="secondary">
                Aynı cihaz için ikinci bir iş açmak istediğinizden emin misiniz?
              </Typography.Text>
            </Space>
          ),
          okText: "Yine de aç",
          cancelText: "Vazgeç",
          onOk: () => yeniKaydet(v, true),
        });
        return;
      }
      message.error((e as Error).message);
    }
  }

  async function duzenlemeKaydet(v: FormDegeri) {
    if (!mevcut) return;
    const g = govdeKur(v);
    const degisen: Record<string, unknown> = { version: mevcut.version };
    const alanlar: (keyof IsGirdisi)[] = [
      "konu",
      "aciklama",
      "oncelik",
      "tur",
      "proje",
      "sistem",
      "talep_kanali",
      "reported_at",
      "iletisim_ad",
      "iletisim_telefon",
    ];
    const eski: Record<string, unknown> = {
      konu: mevcut.konu,
      aciklama: mevcut.aciklama,
      oncelik: mevcut.oncelik,
      tur: mevcut.tur,
      proje: mevcut.proje,
      sistem: mevcut.sistem,
      talep_kanali: mevcut.talep_kanali,
      reported_at: mevcut.reported_at ? dayjs(mevcut.reported_at).toISOString() : null,
      iletisim_ad: mevcut.iletisim_ad,
      iletisim_telefon: mevcut.iletisim_telefon,
    };
    for (const a of alanlar) if ((g[a] ?? null) !== (eski[a] ?? null)) degisen[a] = g[a];
    // Maskeli telefon geri gönderilmez (yetkisi olmayan görmüş olur, değiştirmemiştir).
    if (typeof degisen.iletisim_telefon === "string" && degisen.iletisim_telefon.includes("*"))
      delete degisen.iletisim_telefon;
    if (musteriDuzeltebilir) {
      if (g.customer_id !== mevcut.customer_id) degisen.customer_id = g.customer_id;
      if ((g.address_id ?? null) !== (mevcut.address_id ?? null)) degisen.address_id = g.address_id;
    }
    if (kategoriDuzeltebilir && v.kategori && v.kategori !== mevcut.kategori) {
      degisen.kategori = v.kategori;
    }
    if (nitelikSorulur(mevcut.birim, v.tur)) {
      const yeni = [...(v.nitelikler ?? [])].sort().join(",");
      const eskiN = [...(mevcut.nitelikler ?? [])].sort().join(",");
      if (yeni !== eskiN) degisen.nitelikler = v.nitelikler ?? [];
    }
    if (kapali || v.gerekce || degisen.kategori) degisen.gerekce = v.gerekce?.trim() || undefined;
    const ayrik = seriAyir(v);
    const yeniSeriler = ayrik.tum;
    const eskiSeriler = mevcut.seriler.map((s) => s.seri_no);
    const seriDegisti = JSON.stringify(yeniSeriler) !== JSON.stringify(eskiSeriler);
    try {
      let sonuc: IsDetayi = mevcut;
      if (Object.keys(degisen).length > 1 || degisen.gerekce) {
        sonuc = await teknikServisApi.guncelle(mevcut.id, degisen);
      }
      if (seriDegisti) {
        sonuc = await teknikServisApi.seriler(
          mevcut.id,
          ayrik.duz,
          v.gerekce?.trim() || undefined,
          ayrik.okumalar,
        );
      }
      message.success("Kaydedildi");
      onKaydedildi(sonuc);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && /yenile|sürüm|değiş/i.test(e.message)) {
        message.warning(`${e.message} — kayıt yeniden yüklendi, değişikliğinizi tekrar yapın.`);
        onCakisma?.();
        return;
      }
      message.error((e as Error).message);
    }
  }

  async function gonder(v: FormDegeri) {
    if (!v.musteri?.musteriId) {
      message.error("Müşteri seçin");
      return;
    }
    setGonderiliyor(true);
    try {
      if (duzenleme) await duzenlemeKaydet(v);
      else await yeniKaydet(v);
    } finally {
      setGonderiliyor(false);
    }
  }

  const turler = (formVerileri?.turler ?? []).filter(
    (t) => (t.ekrandan || t.kod === mevcut?.tur) && (!yalnizKurulum || t.kod === KURULUM),
  );

  if (sozlukBekleniyor) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12, padding: 48 }}>
        <Spin />
        <Typography.Text type="secondary">Form hazırlanıyor (birim ve iş türleri yükleniyor)…</Typography.Text>
      </div>
    );
  }

  return (
    <Form<FormDegeri> form={form} layout="vertical" onFinish={(v) => void gonder(v)} disabled={gonderiliyor}>
      {kapali && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="Kapalı işte düzeltme yalnız kapatma yetkisiyle ve gerekçeyle yapılır."
        />
      )}
      <Row gutter={12}>
        <Col xs={24} sm={12}>
          <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
            <Select
              disabled={duzenleme}
              options={(formVerileri?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item name="tur" label="İş türü" rules={[{ required: true, message: "Tür seçin" }]}>
            <Select
              disabled={mevcut?.tur === "PB" || yalnizKurulum}
              options={turler.map((t) => ({ value: t.kod, label: t.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item name="oncelik" label="Öncelik">
            <Radio.Group
              optionType="button"
              options={(formVerileri?.oncelikler ?? ["KRITIK", "YUKSEK", "NORMAL"]).map((o) => ({
                value: o,
                label: ONCELIK_ADLARI[o] ?? o,
              }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name="talep_kanali"
            label="Talep kanalı"
            rules={[{ required: true, message: "Talep kanalı seçin" }]}
          >
            <Select
              options={(formVerileri?.talep_kanallari ?? [])
                .filter((k) => k.kod !== "BAKIM_OTOMATIK")
                .map((k) => ({ value: k.kod, label: k.ad }))}
            />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item
        name="musteri"
        label="Müşteri ve lokasyon"
        extra={duzenleme ? undefined : "Lokasyon isteğe bağlı (elden ya da kargoyla gelen cihazda boş bırakılabilir)."}
        rules={[
          {
            validator: (_, v: MusteriLokasyonSecimi | undefined) =>
              !v?.musteriId
                ? Promise.reject(new Error("Müşteri seçin"))
                : Promise.resolve(),
          },
        ]}
      >
        <MusteriLokasyonSecici disabled={!musteriDuzeltebilir} onSahaOnerisi={sahaOnerisi} />
      </Form.Item>

      {irtibatlar.length > 0 && (
        <Form.Item label="Lokasyon irtibatından seç">
          <Select
            allowClear
            placeholder="İrtibat seçin (isteğe bağlı)"
            value={
              irtibatlar.some((k) => k.id === onerilenIrtibat?.id) ? onerilenIrtibat?.id : undefined
            }
            onChange={(id?: number) => (id ? irtibatSec(id) : undefined)}
            options={irtibatlar.map((k) => ({
              value: k.id,
              label: [k.ad, k.unvan].filter(Boolean).join(" · "),
            }))}
          />
        </Form.Item>
      )}
      <Row gutter={12}>
        <Col xs={24} sm={12}>
          <Form.Item
            name="iletisim_ad"
            label="Talep eden kişi"
            extra={onerilenIrtibat ? `Lokasyonun birincil irtibatı: ${onerilenIrtibat.ad}` : undefined}
            rules={duzenleme ? [] : [{ required: true, whitespace: true, message: "Talep eden kişinin adı zorunlu" }]}
          >
            <Input maxLength={120} placeholder="Ad Soyad" />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name="iletisim_telefon"
            label="Telefon"
            rules={duzenleme ? [] : [{ required: true, whitespace: true, message: "Telefon zorunlu" }]}
          >
            <Input maxLength={20} inputMode="tel" placeholder="05xx xxx xx xx" />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item
        name="konu"
        label="Arıza tanımı / konu"
        rules={[{ required: true, whitespace: true, max: 200, message: "Arıza tanımı zorunlu (en çok 200 karakter)" }]}
      >
        <Input placeholder="Ör. Kamera görüntü vermiyor" />
      </Form.Item>
      <Form.Item name="aciklama" label="Açıklama">
        <Input.TextArea rows={3} maxLength={4000} />
      </Form.Item>
      <Form.Item
        name="seriler"
        label={tekCihaz ? "Cihaz seri numarası" : "Cihazlar (seri numaraları)"}
        required={okutmaZorunlu && !duzenleme}
        extra={
          (okutmaZorunlu ? "Cihazın barkodunu el okuyucuyla ya da kamera düğmesiyle okutun. " : "") +
          (tekCihaz
            ? "Planlı bakımda tek cihaz olur."
            : "Birden çok cihaz eklenebilir; her seriyi okutun ya da yazıp Enter'a basın.")
        }
        rules={[
          {
            validator: (_, v: string[] | undefined) => {
              const dolu = (v ?? []).filter((s) => s.trim());
              if (tekCihaz && dolu.length > 1)
                return Promise.reject(new Error("Planlı bakımda tek cihaz olur"));
              if (okutmaZorunlu && !duzenleme && !dolu.length)
                return Promise.reject(
                  new Error("Cihazlı işte seri zorunlu: barkodu okutun ya da elle girip nedenini seçin"),
                );
              return Promise.resolve();
            },
          },
        ]}
      >
        <SeriOkutucu
          placeholder="Barkodu okutun (kamera düğmesi) ya da seriyi yazıp Enter'a basın"
          disabled={mevcut?.tur === "PB"}
          etiketler={seriEtiketleri}
          onOkuma={(seri, k) => setKaynaklar((x) => ({ ...x, [seriAnahtari(seri)]: k }))}
        />
      </Form.Item>
      {okutmaZorunlu && elleSeriVar && (
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item
              name="elle_gerekce"
              label="Seri okutulmadı: neden?"
              rules={[{ required: true, message: "Elle girilen seri için neden seçin" }]}
            >
              <Select options={ELLE_GEREKCELERI.map((g) => ({ value: g.kod, label: g.ad }))} />
            </Form.Item>
          </Col>
          {elleGerekce === "DIGER" && (
            <Col xs={24} sm={12}>
              <Form.Item
                name="elle_aciklama"
                label="Açıklama"
                rules={[{ required: true, whitespace: true, message: "Açıklama yazın" }]}
              >
                <Input maxLength={200} />
              </Form.Item>
            </Col>
          )}
        </Row>
      )}
      {kutukBirimi && (kutukCihazlari.data?.length ?? 0) > 0 && (
        <Form.Item
          label="Kütükteki cihazdan seç"
          extra={
            seciliKutuk?.frekans?.role_tx
              ? `Kayıtlı frekans: TX ${seciliKutuk.frekans.role_tx} / RX ${seciliKutuk.frekans.role_rx ?? "—"} (işe otomatik gelir)`
              : birim === "HABERLESME"
                ? "Kayıtlı frekansı olmayan cihazda iş kapatılmadan teknisyen frekansı girer."
                : "Seri numarası kütükten gelir; kütükte yoksa iş kapatılmadan teknisyen girer."
          }
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Cihaz seçin (seri numarası alana yazılır)"
            value={seciliKutuk?.id}
            disabled={mevcut?.tur === "PB"}
            onChange={(id?: number) => {
              const c = kutukCihazlari.data?.find((x) => x.id === id);
              // Çoklu cihaz (2026-11-24): kütükten seçilen seri listeye EKLENİR.
              const mevcutSeriler: string[] = form.getFieldValue("seriler") ?? [];
              if (c?.serial_no && !mevcutSeriler.some((x) => seriAnahtari(x) === seriAnahtari(c.serial_no!)))
                form.setFieldValue("seriler", tekCihaz ? [c.serial_no] : [...mevcutSeriler, c.serial_no]);
              // Kütükten seçilen seri okutulmuş sayılmaz (cihaz yanında değil).
              if (c?.serial_no) setKaynaklar((x) => ({ ...x, [seriAnahtari(c.serial_no!)]: "ELLE" }));
            }}
            options={(kutukCihazlari.data ?? [])
              .filter((c) => c.serial_no)
              .map((c) => ({
                value: c.id,
                label: [
                  KUTUK_TIP_ADI[c.equipment_type] ?? c.equipment_type,
                  [c.brand, c.model].filter(Boolean).join(" "),
                  c.serial_no,
                  c.frekans?.role_tx ? `TX ${c.frekans.role_tx} / RX ${c.frekans.role_rx ?? "—"}` : "",
                ]
                  .filter(Boolean)
                  .join(" · "),
              }))}
          />
        </Form.Item>
      )}
      {!duzenleme && (seriler ?? []).filter((x) => x.trim()).length > 0 && (
        <Form.Item
          label="Cihaz bilgileri"
          extra="Müşteri şikâyeti ve notlar yalnız personele görünür; cihaz durumu ve onarım bilgisi onarım fişine basılır."
        >
          <Space orientation="vertical" style={{ width: "100%" }} size={8}>
            {(seriler ?? [])
              .filter((x) => x.trim())
              .map((seri, i) => (
                <Card key={seriAnahtari(seri)} size="small" title={`Cihaz ${i + 1} · ${seri}`}>
                  <CihazBilgisiAlanlari onek={["cihaz_bilgileri", seriAnahtari(seri)]} />
                </Card>
              ))}
          </Space>
        </Form.Item>
      )}
      <MukerrerUyarisi m={mukerrer} />

      <Row gutter={12} style={{ marginTop: 12 }}>
        <Col xs={24} sm={12}>
          <Form.Item
            name="reported_at"
            label="Bildirim anı"
            extra={gecis ? "Geçiş kaydı: kaynaktaki asıl tarih girilir." : "En çok 7 gün geriye girilebilir."}
          >
            <DatePicker
              showTime={{ format: "HH:mm" }}
              format="DD.MM.YYYY HH:mm"
              style={{ width: "100%" }}
              disabledDate={(d) =>
                d.isAfter(dayjs(), "day") || (!gecis && d.isBefore(dayjs().subtract(7, "day"), "day"))
              }
            />
          </Form.Item>
        </Col>
        <Col xs={12} sm={6}>
          <Form.Item name="proje" label="Proje">
            <Input maxLength={120} />
          </Form.Item>
        </Col>
        <Col xs={12} sm={6}>
          <Form.Item name="sistem" label="Sistem">
            <Input maxLength={120} />
          </Form.Item>
        </Col>
      </Row>

      {nitelikVar && (
        <Form.Item
          name="nitelikler"
          label="İşin niteliği"
          extra="Birden çok seçilebilir. Kurulum ya da montaj seçilirse röle montaj bilgileri doldurulmadan iş kapatılamaz."
          rules={[{ required: true, type: "array", min: 1, message: "İşin niteliğini seçin" }]}
        >
          <Checkbox.Group options={HABERLESME_NITELIKLERI.map((n) => ({ value: n.kod, label: n.ad }))} />
        </Form.Item>
      )}

      {gecisYetkili && (
        <>
          <Form.Item name="gecis_kaydi" valuePropName="checked" style={{ marginBottom: gecis ? 8 : undefined }}>
            <Checkbox>Geçmiş kayıt (geçiş) — eski bildirim tarihi korunur, SLA ölçülmez</Checkbox>
          </Form.Item>
          {gecis && (
            <Form.Item
              name="gecis_gerekcesi"
              label="Geçiş gerekçesi"
              rules={[
                {
                  validator: (_, v: string | undefined) =>
                    (v ?? "").trim().length >= GECIS_GEREKCE_ALT
                      ? Promise.resolve()
                      : Promise.reject(new Error(`Gerekçe zorunlu (en az ${GECIS_GEREKCE_ALT} karakter)`)),
                },
              ]}
            >
              <Input maxLength={500} placeholder="Ör. Eski talep listesinden aktarım (Excel, Ekim 2026)" />
            </Form.Item>
          )}
        </>
      )}

      {!duzenleme && uzaktanYetkili && (
        <>
          <Divider style={{ margin: "8px 0 12px" }} />
          <Form.Item name="uzaktan" valuePropName="checked" label="Açılışta çözüldü">
            <Switch checkedChildren="Telefonla/uzaktan çözüldü" unCheckedChildren="Hayır" />
          </Form.Item>
          {uzaktan && (
            <>
              <Form.Item name="cozum_kanali" label="Çözüm kanalı" initialValue="TELEFON">
                <Radio.Group
                  optionType="button"
                  options={[
                    { value: "TELEFON", label: "Telefonla" },
                    { value: "UZAKTAN", label: "Uzaktan bağlantı" },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="yapilan_islem"
                label="Yapılan işlem"
                rules={[{ required: true, whitespace: true, message: "Yapılan işlemi yazın" }]}
              >
                <Input.TextArea rows={2} maxLength={4000} />
              </Form.Item>
              <Form.Item name="ariza_nedeni_id" label="Arıza nedeni">
                <Select
                  allowClear
                  loading={arizaNedenleri.isFetching}
                  options={(arizaNedenleri.data ?? [])
                    .filter((n) => n.is_active)
                    .map((n) => ({ value: n.id, label: n.ad }))}
                />
              </Form.Item>
            </>
          )}
        </>
      )}

      {tayinYetkili && !uzaktan && (
        <>
          <Divider style={{ margin: "8px 0 12px" }} />
          <Row gutter={12}>
            <Col xs={24} sm={14}>
              <Form.Item
                name="tayin_kisiler"
                label="Personel tayini"
                extra="İsteğe bağlı. Boş bırakılırsa iş tayin bekler."
              >
                <Select
                  mode="multiple"
                  allowClear
                  placeholder={birim ? "Personel seçin" : "Önce birim seçin"}
                  disabled={!birim}
                  loading={tayinAdaylari.isFetching}
                  optionFilterProp="label"
                  onChange={(v: number[]) => {
                    const s = form.getFieldValue("tayin_sorumlu");
                    if (s && !v.includes(s)) form.setFieldValue("tayin_sorumlu", undefined);
                  }}
                  options={(tayinAdaylari.data ?? []).map((k) => ({
                    value: k.id,
                    label: `${k.ad}${k.giris_acik ? "" : " (girişsiz)"} · ${k.saha_rolu}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={10}>
              <Form.Item
                name="tayin_sorumlu"
                label="Sorumlu"
                extra={(tayinKisiler?.length ?? 0) === 1 ? "Tek kişi seçildiyse sorumlu odur." : undefined}
              >
                <Select
                  allowClear
                  disabled={!tayinKisiler?.length}
                  options={(tayinAdaylari.data ?? [])
                    .filter((k) => tayinKisiler?.includes(k.id))
                    .map((k) => ({ value: k.id, label: k.ad }))}
                />
              </Form.Item>
            </Col>
          </Row>
        </>
      )}

      {kategoriDuzeltebilir && (
        <Form.Item
          name="kategori"
          label="Kategori"
          extra="Türden türetilir; yalnız gerekçeyle düzeltilir."
        >
          <Select
            options={(formVerileri?.kategoriler ?? [])
              .filter((k) => k.kod !== "PLANLI_BAKIM")
              .map((k) => ({ value: k.kod, label: k.ad }))}
          />
        </Form.Item>
      )}
      {duzenleme && (
        <Form.Item
          name="gerekce"
          label="Düzeltme gerekçesi"
          rules={
            kapali || (kategoriDuzeltebilir && kategoriDegeri && kategoriDegeri !== mevcut?.kategori)
              ? [{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]
              : []
          }
        >
          <Input maxLength={500} placeholder={kapali ? "Zorunlu" : "Müşteri/seri düzeltmesinde önerilir"} />
        </Form.Item>
      )}

      <Space style={{ width: "100%", justifyContent: "flex-end" }}>
        <Button onClick={onVazgec}>Vazgeç</Button>
        <Button type="primary" htmlType="submit" loading={gonderiliyor}>
          {duzenleme ? "Kaydet" : "İşi aç"}
        </Button>
      </Space>
    </Form>
  );
}

