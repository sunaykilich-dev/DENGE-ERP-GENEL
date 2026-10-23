/**
 * Fiori Launchpad (Başlangıç sayfası) — rehber §2.
 *
 * Üstte yapışkan sekme (anchor) çubuğu: grup adları, seçili olan mavi altı
 * çizili; tıklamak ilgili grubun başlığına kaydırır. Altında gruplar ve
 * kutucuklar. Kutucuk yalnız kullanıcı yetkiliyse görünür (katalog izni);
 * KPI sayıları mevcut uçlardan gelir ve ekran sayı HESAPLAMAZ.
 */
import { useQuery } from "@tanstack/react-query";
import { Empty, Modal, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { servisZaman } from "../api/servisZaman";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import { fiori } from "../theme";
import { type GrupKodu, type Uygulama, gorunurGruplar } from "./uygulamalar";

interface Uyari {
  kod: string;
  baslik: string;
  adet: number;
  yol: string;
  onem: "bilgi" | "uyari" | "kritik";
  aciklama: string;
}

interface UyariOzeti {
  toplam: number;
  uyarilar: Uyari[];
}

const ONEM_RENGI: Record<string, string> = { kritik: "red", uyari: "orange", bilgi: "blue" };

/** Uyarı zili ile AYNI sorgu anahtarı: önbellek paylaşılır, ikinci istek atılmaz. */
export const uyariSorgusu = {
  queryKey: ["uyarilar"],
  queryFn: () => api.get<UyariOzeti>("/api/raporlar/uyarilar"),
  refetchInterval: 60_000,
  staleTime: 30_000,
};

export interface KpiDegeri {
  deger: number | null;
  yukleniyor: boolean;
  vurgu?: "normal" | "uyari" | "kritik";
  /** Sunucunun verdiği "sayı = liste" yolu. */
  yol?: string;
}

/** Görünür kutucukların KPI'ları; yalnız gereken uç, yalnız yetkiliyse çağrılır. */
function useKpiler(uygulamalar: Uygulama[]): (u: Uygulama) => KpiDegeri | null {
  const panelGerekli = uygulamalar.some((u) => u.kpi?.tur === "panel");
  const benimGerekli = uygulamalar.some((u) => u.kpi?.tur === "benim");
  const uyariGerekli = uygulamalar.some((u) => u.kpi?.tur === "uyari");

  // Servis Paneli ile aynı anahtar ("ay" varsayılan dönemi): anlık kutular
  // dönemden bağımsızdır, panel sayfası açılınca önbellek yeniden kullanılır.
  const panel = useQuery({
    queryKey: ["servis-paneli", "ay"],
    queryFn: () => teknikServisApi.panel("ay"),
    enabled: panelGerekli,
    staleTime: 60_000,
  });
  const benim = useQuery({
    queryKey: ["benim-islerim", "benim"],
    queryFn: () => servisZaman.benimIslerim("benim"),
    enabled: benimGerekli,
    staleTime: 60_000,
  });
  const uyari = useQuery({ ...uyariSorgusu, enabled: uyariGerekli });

  return useCallback(
    (u: Uygulama): KpiDegeri | null => {
      const k = u.kpi;
      if (!k) return null;
      if (k.tur === "panel") {
        if (panel.isError) return null;
        const kutu = panel.data?.kutular.find((x) => x.kod === k.kod);
        if (panel.data && !kutu) return null;
        return {
          deger: kutu?.deger ?? null,
          yukleniyor: panel.isLoading,
          vurgu: kutu?.vurgu,
          yol: kutu?.yol,
        };
      }
      if (k.tur === "benim") {
        if (benim.isError) return null;
        const adet = benim.data
          ? benim.data.gruplar.reduce(
              (n, g) => n + g.ziyaretler.reduce((m, z) => m + z.isler.length, 0),
              0,
            )
          : null;
        return { deger: adet, yukleniyor: benim.isLoading };
      }
      if (uyari.isError) return null;
      const liste = uyari.data?.uyarilar ?? [];
      return {
        deger: uyari.data ? liste.length : null,
        yukleniyor: uyari.isLoading,
        vurgu: liste.some((x) => x.onem === "kritik")
          ? "kritik"
          : liste.length
            ? "uyari"
            : "normal",
      };
    },
    [panel.data, panel.isError, panel.isLoading, benim.data, benim.isError, benim.isLoading, uyari.data, uyari.isError, uyari.isLoading],
  );
}

const VURGU_RENGI: Record<string, string> = {
  normal: fiori.metin,
  uyari: fiori.turuncu,
  kritik: fiori.kirmizi,
};

function KutucukIcerigi({ u, kpi }: { u: Uygulama; kpi: KpiDegeri | null }) {
  const Ikon = u.ikon;
  return (
    <>
      <div className="fiori-kutucuk-ust">
        <div className="fiori-kutucuk-baslik">{u.baslik}</div>
        {u.altBaslik && <div className="fiori-kutucuk-alt">{u.altBaslik}</div>}
      </div>
      <div className="fiori-kutucuk-alt-satir">
        <Ikon className="fiori-kutucuk-ikon" />
        {kpi && (
          <span
            className="fiori-kutucuk-kpi"
            style={{ color: kpi.deger ? VURGU_RENGI[kpi.vurgu ?? "normal"] : fiori.metin }}
          >
            {kpi.yukleniyor || kpi.deger === null ? "…" : kpi.deger.toLocaleString("tr-TR")}
          </span>
        )}
      </div>
      {kpi && u.kpiBirimi && <div className="fiori-kutucuk-birim">{u.kpiBirimi}</div>}
    </>
  );
}

function Kutucuk({
  u,
  kpi,
  uyarilariAc,
}: {
  u: Uygulama;
  kpi: KpiDegeri | null;
  uyarilariAc: () => void;
}) {
  if (u.kpi?.tur === "uyari") {
    return (
      <button type="button" className="fiori-kutucuk" onClick={uyarilariAc} title={u.baslik}>
        <KutucukIcerigi u={u} kpi={kpi} />
      </button>
    );
  }
  return (
    <Link to={kpi?.yol ?? u.yol} className="fiori-kutucuk" title={u.baslik}>
      <KutucukIcerigi u={u} kpi={kpi} />
    </Link>
  );
}

function UyariPenceresi({ acik, kapat }: { acik: boolean; kapat: () => void }) {
  const navigate = useNavigate();
  const { data } = useQuery({ ...uyariSorgusu, enabled: acik });
  const liste = data?.uyarilar ?? [];
  return (
    <Modal open={acik} onCancel={kapat} footer={null} title="Uyarılar" destroyOnHidden>
      {liste.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Bekleyen uyarı yok" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {liste.map((u) => (
            <button
              key={u.kod}
              type="button"
              className="fiori-uyari-satiri"
              onClick={() => {
                kapat();
                navigate(u.yol);
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Tag color={ONEM_RENGI[u.onem]} style={{ marginInlineEnd: 0 }}>
                  {u.adet}
                </Tag>
                <span style={{ fontWeight: 600, color: fiori.mavi }}>{u.baslik}</span>
              </span>
              {u.aciklama && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {u.aciklama}
                </Typography.Text>
              )}
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

export const grupBolumKimligi = (kod: GrupKodu) => `fiori-grup-${kod}`;

/**
 * @param ilkGrup Açılışta kaydırılacak grup (rol bazlı açılış kuralının
 *   karşılığı). İlk görünür grup ise kaydırma yapılmaz.
 */
export default function Launchpad({ ilkGrup }: { ilkGrup?: GrupKodu | null }) {
  const { yetkili } = useAuth();
  const gruplar = useMemo(() => gorunurGruplar(yetkili), [yetkili]);
  const tumKutucuklar = useMemo(() => gruplar.flatMap((g) => g.uygulamalar), [gruplar]);
  const kpi = useKpiler(tumKutucuklar);
  const [aktif, setAktif] = useState<GrupKodu | undefined>(gruplar[0]?.grup.kod);
  const [uyariAcik, setUyariAcik] = useState(false);
  const cubuk = useRef<HTMLDivElement>(null);
  // Sekmeye tıklanınca kaydırma bitene kadar kaydırma dinleyicisi sekmeyi değiştirmesin.
  const elleSecim = useRef<number>(0);

  const sekmeyeGit = useCallback((kod: GrupKodu, davranis: ScrollBehavior = "smooth") => {
    const bolum = document.getElementById(grupBolumKimligi(kod));
    if (!bolum) return;
    setAktif(kod);
    elleSecim.current = Date.now();
    bolum.scrollIntoView({ behavior: davranis, block: "start" });
  }, []);

  // Rol bazlı açılış: ilgili sekmeye kaydır (ilk grup zaten en üstte).
  useEffect(() => {
    const hedef =
      (window.location.hash.replace("#", "") as GrupKodu) || ilkGrup || undefined;
    if (!hedef || hedef === gruplar[0]?.grup.kod) return;
    if (!gruplar.some((g) => g.grup.kod === hedef)) return;
    const t = window.setTimeout(() => sekmeyeGit(hedef, "auto"), 0);
    return () => window.clearTimeout(t);
    // Yalnız ilk çizimde.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Kaydırırken üstte kalan grubun sekmesi seçili görünsün (Fiori anchor bar).
  useEffect(() => {
    const dinle = () => {
      if (Date.now() - elleSecim.current < 800) return;
      const esik = (cubuk.current?.getBoundingClientRect().bottom ?? 100) + 24;
      let secilen = gruplar[0]?.grup.kod;
      for (const g of gruplar) {
        const el = document.getElementById(grupBolumKimligi(g.grup.kod));
        if (el && el.getBoundingClientRect().top <= esik) secilen = g.grup.kod;
      }
      // Sayfa sonuna inildiyse son grup.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        secilen = gruplar[gruplar.length - 1]?.grup.kod;
      }
      setAktif(secilen);
    };
    window.addEventListener("scroll", dinle, { passive: true });
    return () => window.removeEventListener("scroll", dinle);
  }, [gruplar]);

  // Seçili sekme dar ekranda görünür alana kaysın.
  useEffect(() => {
    const el = cubuk.current?.querySelector<HTMLElement>(`[data-grup="${aktif}"]`);
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [aktif]);

  if (gruplar.length === 0) {
    return (
      <div className="fiori-lp-bos">
        <Empty description="Hesabınıza tanımlı bir uygulama yok. Yöneticinizden yetki isteyin." />
      </div>
    );
  }

  return (
    <div className="fiori-lp">
      <div className="fiori-lp-sekmeler" ref={cubuk} role="tablist" aria-label="Uygulama grupları">
        {gruplar.map(({ grup }) => (
          <button
            key={grup.kod}
            type="button"
            role="tab"
            aria-selected={aktif === grup.kod}
            data-grup={grup.kod}
            className={`fiori-lp-sekme${aktif === grup.kod ? " secili" : ""}`}
            onClick={() => sekmeyeGit(grup.kod)}
          >
            {grup.baslik}
          </button>
        ))}
      </div>

      <div className="fiori-lp-icerik">
        {gruplar.map(({ grup, uygulamalar }, i) => (
          <section
            key={grup.kod}
            id={grupBolumKimligi(grup.kod)}
            className="fiori-lp-grup"
            aria-label={grup.baslik}
          >
            {/* Fiori'de ilk grubun adı yalnız sekme çubuğunda görünür. */}
            {i > 0 && <h2 className="fiori-lp-grup-baslik">{grup.baslik}</h2>}
            <div className="fiori-lp-kutucuklar">
              {uygulamalar.map((u) => (
                <Kutucuk key={u.id} u={u} kpi={kpi(u)} uyarilariAc={() => setUyariAcik(true)} />
              ))}
            </div>
          </section>
        ))}
      </div>

      <UyariPenceresi acik={uyariAcik} kapat={() => setUyariAcik(false)} />
    </div>
  );
}
