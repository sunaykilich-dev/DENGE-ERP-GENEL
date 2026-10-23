/**
 * Fiori durum filtre çubuğu (rehber §3.3): tek satır, ince kenarlı grup —
 * [👤 bana tayin edilenler] [⟳ yenile] YENİ TAYİN İŞLEM … [▽+ gelişmiş süzgeç].
 * Metin düğmeler BÜYÜK HARF Fiori mavisi; seçili olan altı çizili. Seçili
 * gruba yeniden basmak süzgeci kaldırır. Dar ekranda çubuk yatay kayar.
 */
import { FilterOutlined, ReloadOutlined, UserOutlined } from "@ant-design/icons";
import { Badge, Tooltip } from "antd";

import { TAYIN, type FioriDurumGrubu } from "./etiketler";
import "./fiori.css";

export interface DurumCubuguProps {
  gruplar: FioriDurumGrubu[];
  secili?: string;
  onSec: (kod: string | undefined) => void;
  /** Verilmezse 👤 düğmesi çizilmez. */
  banaAit?: boolean;
  onBanaAit?: (v: boolean) => void;
  banaAitIpucu?: string;
  onYenile?: () => void;
  yenileniyor?: boolean;
  /** Gelişmiş süzgeç paneli aç/kapa; verilmezse ▽+ çizilmez. */
  onSuzgec?: () => void;
  suzgecAcik?: boolean;
  /** Etkin gelişmiş süzgeç sayısı (rozet). */
  suzgecSayisi?: number;
}

export default function DurumCubugu({
  gruplar,
  secili,
  onSec,
  banaAit,
  onBanaAit,
  banaAitIpucu = TAYIN.banaTayinEdilenler,
  onYenile,
  yenileniyor,
  onSuzgec,
  suzgecAcik,
  suzgecSayisi = 0,
}: DurumCubuguProps) {
  return (
    <div className="fl-durum-cubugu-sarici">
      <div className="fl-durum-cubugu" role="toolbar" aria-label="Durum süzgeci">
        {onBanaAit && (
          <Tooltip title={banaAitIpucu}>
            <button
              type="button"
              className={`fl-cubuk-ikon${banaAit ? " secili" : ""}`}
              aria-pressed={!!banaAit}
              aria-label={banaAitIpucu}
              onClick={() => onBanaAit(!banaAit)}
            >
              <UserOutlined />
            </button>
          </Tooltip>
        )}
        {onYenile && (
          <Tooltip title="Yenile">
            <button type="button" className="fl-cubuk-ikon kenarli" aria-label="Yenile" onClick={onYenile}>
              <ReloadOutlined spin={!!yenileniyor} />
            </button>
          </Tooltip>
        )}
        {gruplar.map((g) => (
          <button
            key={g.kod}
            type="button"
            className={`fl-durum-dugme${g.kod === secili ? " secili" : ""}`}
            aria-pressed={g.kod === secili}
            onClick={() => onSec(g.kod === secili ? undefined : g.kod)}
          >
            {g.ad}
          </button>
        ))}
        {onSuzgec && (
          <Tooltip title="Gelişmiş süzgeç">
            <button
              type="button"
              className={`fl-cubuk-ikon${suzgecAcik ? " secili" : ""}`}
              aria-expanded={!!suzgecAcik}
              aria-label="Gelişmiş süzgeç"
              onClick={onSuzgec}
            >
              <Badge count={suzgecSayisi} size="small" offset={[6, -4]}>
                <FilterOutlined style={{ color: "inherit" }} />
              </Badge>
              <span style={{ fontSize: 11, marginLeft: 1 }}>+</span>
            </button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
