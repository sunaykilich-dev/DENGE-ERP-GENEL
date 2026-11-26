/**
 * El okuyucu (USB/Bluetooth, klavye gibi çalışan) algılama — TEK yardımcı.
 *
 * Okuyucu kodu klavye gibi yazar ve Enter'a basar; insan bu hızda yazamaz.
 * Her karakter bir öncekinden en çok `OKUYUCU_AZAMI_ARALIK_MS` sonra gelmiş,
 * en az `OKUYUCU_ASGARI_UZUNLUK` karakter yazılmış ve Enter son karakterden
 * hemen sonra gelmişse giriş OKUTMA sayılır; yapıştırma, silme ya da yavaş
 * yazma ELLE'dir. Kamera okuması kaynağı doğrudan OKUTMA verir.
 *
 * Sunucu gerçek okutmayı ayıramaz (2026-11-23 sahip kararı): kaynağı istemci
 * işaretler, sunucu yalnız varlığı ve elle girişin nedenini zorlar.
 */
import { useCallback, useRef } from "react";
import type React from "react";

export type OkumaKaynagi = "OKUTMA" | "ELLE";

export const OKUYUCU_AZAMI_ARALIK_MS = 50;
export const OKUYUCU_ASGARI_UZUNLUK = 4;

/** Saf hesap (test edilebilir): tuş zamanları + Enter anı → okuyucu mu? */
export function okuyucuGirisiMi(zamanlar: number[], enterAni: number, uzunluk: number): boolean {
  if (zamanlar.length < OKUYUCU_ASGARI_UZUNLUK || zamanlar.length !== uzunluk) return false;
  for (let i = 1; i < zamanlar.length; i++) {
    if (zamanlar[i] - zamanlar[i - 1] > OKUYUCU_AZAMI_ARALIK_MS) return false;
  }
  return enterAni - zamanlar[zamanlar.length - 1] <= OKUYUCU_AZAMI_ARALIK_MS * 2;
}

/**
 * Bir metin alanına bağlanır: `olaylar` Input'a yayılır, Enter anında
 * `kaynak(deger)` girişin OKUTMA mı ELLE mi olduğunu söyler ve sayaçları sıfırlar.
 */
export function useOkuyucuAlgilama() {
  const zamanlar = useRef<number[]>([]);
  const bozuldu = useRef(false);

  const sifirla = useCallback(() => {
    zamanlar.current = [];
    bozuldu.current = false;
  }, []);

  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") return;
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      zamanlar.current.push(e.timeStamp || performance.now());
    } else if (e.key === "Backspace" || e.key === "Delete") {
      bozuldu.current = true;
    }
  }, []);

  const onPaste = useCallback(() => {
    bozuldu.current = true;
  }, []);

  const kaynak = useCallback(
    (deger: string, enterAni: number = performance.now()): OkumaKaynagi => {
      const okuyucu =
        !bozuldu.current && okuyucuGirisiMi(zamanlar.current, enterAni, deger.trim().length);
      zamanlar.current = [];
      bozuldu.current = false;
      return okuyucu ? "OKUTMA" : "ELLE";
    },
    [],
  );

  return { olaylar: { onKeyDown, onPaste }, kaynak, sifirla };
}
