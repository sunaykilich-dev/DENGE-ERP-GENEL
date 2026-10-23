/**
 * Fiori alt eylem çubuğu (footer toolbar, rehber §3.5): sayfa altına yapışık
 * beyaz çubuk; solda metin düğmeler (Liste, Saat Aç, Saat Kapa), ardından
 * ikon düğmeler (Tayin Et, İptal, Düzenle, PDF), sağda vurgulu eylemler.
 * Seçim gerektiren eylem çağıran tarafından `devreDisi` ile pasifleştirilir;
 * yetkisiz eylem hiç verilmez (`gizli`).
 */
import { Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import type { ReactNode } from "react";

import "./fiori.css";

export interface FioriEylem {
  anahtar: string;
  /** Metin; `yalnizIkon` ise ipucu olarak kullanılır. */
  ad: string;
  ikon?: ReactNode;
  yalnizIkon?: boolean;
  /** Dar ekranda metni gizle (ikon kalır). */
  kisalt?: boolean;
  ipucu?: string;
  onClick?: () => void;
  href?: string;
  devreDisi?: boolean;
  gizli?: boolean;
  tehlikeli?: boolean;
  vurgulu?: boolean;
  yukleniyor?: boolean;
  /** Verilirse düğme açılır menü olur. */
  menu?: MenuProps["items"];
  onMenu?: (anahtar: string) => void;
}

function EylemDugmesi({ e }: { e: FioriEylem }) {
  const sinif = `fl-eylem${e.vurgulu ? " vurgulu" : ""}${e.tehlikeli ? " tehlikeli" : ""}${
    e.devreDisi ? " pasif" : ""
  }`;
  const icerik = (
    <>
      {e.ikon}
      {!e.yalnizIkon && <span className={`fl-eylem-metin${e.kisalt ? " kisalt" : ""}`}>{e.ad}</span>}
    </>
  );
  const ipucu = e.ipucu ?? (e.yalnizIkon || e.kisalt ? e.ad : undefined);
  let dugme: ReactNode;
  if (e.menu) {
    dugme = (
      <Dropdown
        trigger={["click"]}
        disabled={e.devreDisi}
        menu={{ items: e.menu, onClick: ({ key }) => e.onMenu?.(String(key)) }}
      >
        <button type="button" className={sinif} disabled={e.devreDisi} aria-label={e.ad}>
          {icerik}
        </button>
      </Dropdown>
    );
  } else if (e.href && !e.devreDisi) {
    dugme = (
      <a className={sinif} href={e.href} target="_blank" rel="noreferrer" aria-label={e.ad}>
        {icerik}
      </a>
    );
  } else {
    dugme = (
      <button
        type="button"
        className={sinif}
        disabled={e.devreDisi || e.yukleniyor}
        aria-label={e.ad}
        aria-busy={e.yukleniyor || undefined}
        onClick={e.onClick}
      >
        {icerik}
      </button>
    );
  }
  return ipucu ? <Tooltip title={ipucu}>{dugme}</Tooltip> : dugme;
}

export default function AltEylemCubugu({
  sol,
  sag,
  orta,
}: {
  sol: FioriEylem[];
  sag?: FioriEylem[];
  /** Sol eylemlerin yanında bilgi (ör. canlı sayaç). */
  orta?: ReactNode;
}) {
  return (
    <div className="fl-alt-cubuk" role="toolbar" aria-label="Eylemler">
      <div className="fl-alt-grup">
        {sol
          .filter((e) => !e.gizli)
          .map((e) => (
            <EylemDugmesi key={e.anahtar} e={e} />
          ))}
      </div>
      {orta}
      <div className="fl-alt-bosluk" />
      {sag && (
        <div className="fl-alt-grup">
          {sag
            .filter((e) => !e.gizli)
            .map((e) => (
              <EylemDugmesi key={e.anahtar} e={e} />
            ))}
        </div>
      )}
    </div>
  );
}
