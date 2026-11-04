/**
 * Kullanıcı başına tarayıcı tercihleri (menü durumu, favoriler, son açılanlar,
 * liste süzgeçleri) — KARARLAR 2026-11-04 §5.
 *
 * Yalnız kolaylık verisidir: gizli tarama, engellenmiş depolama ya da bozuk
 * JSON'da sessizce varsayılana döner (try/catch), uygulama asla bundan
 * dolayı bozulmaz. Anahtar kullanıcı kimliğini içerir; aynı tarayıcıyı
 * paylaşan iki kullanıcının tercihleri karışmaz. Kişisel veri YAZILMAZ
 * (yalnız menü anahtarları ve süzgeç parametreleri).
 */

const ONEK = "denge-erp";

function anahtar(kullaniciId: number | undefined, ad: string): string {
  return `${ONEK}:${kullaniciId ?? "anonim"}:${ad}`;
}

export function yerelOku<T>(kullaniciId: number | undefined, ad: string, varsayilan: T): T {
  try {
    const ham = window.localStorage.getItem(anahtar(kullaniciId, ad));
    if (ham === null) return varsayilan;
    return JSON.parse(ham) as T;
  } catch {
    return varsayilan;
  }
}

export function yerelYaz(kullaniciId: number | undefined, ad: string, deger: unknown): void {
  try {
    window.localStorage.setItem(anahtar(kullaniciId, ad), JSON.stringify(deger));
  } catch {
    /* depolama kapalı/dolu: tercih bu oturumla sınırlı kalır */
  }
}
