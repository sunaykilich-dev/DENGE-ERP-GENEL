/**
 * "+ Hızlı oluştur" bağlantısı (`?yeni=1`): sayfa mevcut oluşturma
 * penceresini açar ve parametreyi adresten siler (geri tuşu/yenileme
 * pencereyi tekrar açmasın). KARARLAR 2026-11-04 §5.
 */
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

export function useYeniParametresi(ac: () => void, etkin = true): void {
  const [arama, setArama] = useSearchParams();
  const istendi = arama.get("yeni") === "1";
  useEffect(() => {
    if (!istendi || !etkin) return;
    ac();
    const p = new URLSearchParams(arama);
    p.delete("yeni");
    setArama(p, { replace: true });
    // `ac` her çizimde yeni olabilir; yalnız parametre görününce bir kez çalışır.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [istendi, etkin]);
}
