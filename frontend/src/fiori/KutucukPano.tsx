/**
 * Kişiselleştirilebilir kutucuk panosu (2026-11-18, kullanıcı isteği).
 *
 * Ekranların sayı kutucuklarını (`KpiKutucugu`) kompakt bir ızgarada çizer ve
 * kullanıcıya "Düzenle" ile sırayı (sürükle ya da ◀ ▶), boyutu (dar/geniş) ve
 * görünürlüğü değiştirme imkânı verir. Düzen sunucuda kişi + ekran başına
 * saklanır (`/api/ekran-duzeni/{ekran}`), her cihazda aynı görünür.
 *
 * Kullanım: `<div className="fl-kutucuklar">` yerine
 * `<KutucukPano ekran="zaman-takibi">…KpiKutucugu…</KutucukPano>`.
 * Kutucuğun kimliği `kod` özelliği ya da React `key`'idir; kimliksiz çocuk
 * (yükleniyor iskeleti) varken düzenleme kapalıdır. Kişisel düzende olmayan
 * (yeni) kutucuk varsayılan yerinde görünür; artık çizilmeyen kod yok sayılır.
 * Düzen veri açmaz: kutucuk verisi ve izni ekranın kendi ucundadır.
 */
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  ColumnWidthOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  HolderOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Tooltip } from "antd";
import { Children, isValidElement, useMemo, useState, type ReactElement, type ReactNode } from "react";

import { ekranDuzeniApi, type EkranKutusu } from "../api/ekranDuzeni";

interface Oge {
  kod: string | null;
  el: ReactElement;
}

/** `kod` özelliği ya da açık `key` (Children.toArray açık anahtarı ".$" ile önekler). */
function kodu(el: ReactElement): string | null {
  const p = el.props as { kod?: string };
  if (p.kod) return p.kod;
  const k = el.key == null ? "" : String(el.key);
  return k.startsWith(".$") ? k.slice(2) : null;
}

export default function KutucukPano({
  ekran,
  children,
  className,
}: {
  /** Ekran kodu: "zaman-takibi", "servis-planlama"… */
  ekran: string;
  children: ReactNode;
  className?: string;
}) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [duzenle, setDuzenle] = useState(false);
  const [surukle, setSurukle] = useState<string | null>(null);
  const anahtar = ["ekran-duzeni", ekran];
  const duzen = useQuery({
    queryKey: anahtar,
    queryFn: () => ekranDuzeniApi.oku(ekran),
    staleTime: 5 * 60_000,
  });
  const kaydet = useMutation({
    mutationFn: (kutular: EkranKutusu[]) => ekranDuzeniApi.kaydet(ekran, kutular),
    onMutate: (kutular) => qc.setQueryData(anahtar, { ekran, kutular }),
    onError: (e: Error) => {
      message.error(`Düzen kaydedilemedi: ${e.message}`);
      void qc.invalidateQueries({ queryKey: anahtar });
    },
  });
  const sifirla = useMutation({
    mutationFn: () => ekranDuzeniApi.sifirla(ekran),
    onSuccess: (d) => qc.setQueryData(anahtar, d),
    onError: (e: Error) => message.error(e.message),
  });
  const kayitli = duzen.data?.kutular ?? null;

  const ogeler: Oge[] = useMemo(
    () =>
      Children.toArray(children)
        .filter(isValidElement)
        .map((el) => ({ kod: kodu(el as ReactElement), el: el as ReactElement })),
    [children],
  );
  const duzenlenebilir = ogeler.length > 0 && ogeler.every((o) => o.kod !== null);

  // Etkin sıra: kişisel düzendeki kodlar (çizilenler) + düzende olmayan yeniler varsayılan yerinde.
  const sirali: (EkranKutusu & { el: ReactElement })[] = useMemo(() => {
    if (!duzenlenebilir) return ogeler.map((o, i) => ({ kod: o.kod ?? `#${i}`, el: o.el, gizli: false, boyut: "DAR" }));
    const harita = new Map(ogeler.map((o) => [o.kod as string, o.el]));
    const sonuc: (EkranKutusu & { el: ReactElement })[] = [];
    for (const k of kayitli ?? []) {
      const el = harita.get(k.kod);
      if (el) {
        sonuc.push({ ...k, el });
        harita.delete(k.kod);
      }
    }
    for (const [kod, el] of harita) sonuc.push({ kod, el, gizli: false, boyut: "DAR" });
    return sonuc;
  }, [ogeler, kayitli, duzenlenebilir]);

  const yaz = (yeni: (EkranKutusu & { el: ReactElement })[]) =>
    kaydet.mutate(yeni.map(({ kod, gizli, boyut }) => ({ kod, gizli, boyut })));
  const tasi = (kod: string, hedef: number) => {
    const i = sirali.findIndex((x) => x.kod === kod);
    if (i < 0 || hedef < 0 || hedef >= sirali.length || hedef === i) return;
    const yeni = [...sirali];
    const [o] = yeni.splice(i, 1);
    yeni.splice(hedef, 0, o);
    yaz(yeni);
  };
  const degistir = (kod: string, alan: Partial<EkranKutusu>) =>
    yaz(sirali.map((x) => (x.kod === kod ? { ...x, ...alan } : x)));

  const gorunen = duzenle ? sirali : sirali.filter((x) => !x.gizli);
  const gizliSayisi = sirali.filter((x) => x.gizli).length;

  return (
    <div className={`fl-pano${duzenle ? " duzenleniyor" : ""}${className ? ` ${className}` : ""}`}>
      {duzenle && (
        <div className="fl-pano-cubuk">
          <span>
            <HolderOutlined /> Kutucukları sürükleyerek ya da oklarla taşıyın; genişliği ve görünürlüğü değiştirin.
            Değişiklik hemen kaydedilir.
          </span>
          <span className="fl-pano-cubuk-sag">
            <Button size="small" onClick={() => sifirla.mutate()} disabled={!kayitli} loading={sifirla.isPending}>
              Varsayılana dön
            </Button>
            <Button size="small" type="primary" onClick={() => setDuzenle(false)}>
              Bitti
            </Button>
          </span>
        </div>
      )}
      <div className="fl-kutucuklar">
        {gorunen.map((o, i) => (
          <div
            key={o.kod}
            className={`fl-pano-oge${o.boyut === "GENIS" ? " genis" : ""}${o.gizli ? " gizli" : ""}${surukle === o.kod ? " suruklenen" : ""}`}
            draggable={duzenle}
            onDragStart={() => setSurukle(o.kod)}
            onDragEnd={() => setSurukle(null)}
            onDragOver={(e) => duzenle && surukle && e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (surukle) tasi(surukle, i);
              setSurukle(null);
            }}
            // Düzenlerken kutucuğa tıklamak listeye gitmesin.
            onClickCapture={(e) => {
              if (duzenle && !(e.target as HTMLElement).closest(".fl-pano-arac")) {
                e.preventDefault();
                e.stopPropagation();
              }
            }}
          >
            {o.el}
            {duzenle && (
              <div className="fl-pano-arac" role="toolbar" aria-label="Kutucuk düzeni">
                <Tooltip title="Sola al">
                  <Button size="small" type="text" icon={<ArrowLeftOutlined />} disabled={i === 0} onClick={() => tasi(o.kod, i - 1)} aria-label="Sola al" />
                </Tooltip>
                <Tooltip title="Sağa al">
                  <Button size="small" type="text" icon={<ArrowRightOutlined />} disabled={i === gorunen.length - 1} onClick={() => tasi(o.kod, i + 1)} aria-label="Sağa al" />
                </Tooltip>
                <Tooltip title={o.boyut === "GENIS" ? "Dar yap" : "Geniş yap"}>
                  <Button
                    size="small"
                    type={o.boyut === "GENIS" ? "primary" : "text"}
                    ghost={o.boyut === "GENIS"}
                    icon={<ColumnWidthOutlined />}
                    onClick={() => degistir(o.kod, { boyut: o.boyut === "GENIS" ? "DAR" : "GENIS" })}
                    aria-label={o.boyut === "GENIS" ? "Dar yap" : "Geniş yap"}
                  />
                </Tooltip>
                <Tooltip title={o.gizli ? "Göster" : "Gizle"}>
                  <Button
                    size="small"
                    type="text"
                    icon={o.gizli ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                    onClick={() => degistir(o.kod, { gizli: !o.gizli })}
                    aria-label={o.gizli ? "Göster" : "Gizle"}
                  />
                </Tooltip>
              </div>
            )}
          </div>
        ))}
      </div>
      {!duzenle && duzenlenebilir && (
        <Tooltip title={gizliSayisi ? `Kutucukları düzenle (${gizliSayisi} gizli)` : "Kutucukları düzenle"}>
          <Button
            className="fl-pano-duzenle"
            size="small"
            type="text"
            icon={<SettingOutlined />}
            onClick={() => setDuzenle(true)}
            aria-label="Kutucukları düzenle"
          />
        </Tooltip>
      )}
    </div>
  );
}

