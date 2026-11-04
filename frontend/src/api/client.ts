/**
 * API istemcisi.
 *
 * Her isteğe `X-Requested-With: fetch` eklenir — sunucu tarafındaki CSRF
 * korumasının diğer yarısı budur (bkz. backend/app/api/deps.py). Form-post
 * tabanlı cross-site istekler bu başlığı ekleyemez.
 *
 * 409 (çakışma) ve 401 (oturum düştü) çağıranın ayırt edebilmesi için
 * durum koduyla birlikte fırlatılır.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /**
     * Yanıt gövdesinin tamamı (JSON ise). Planlama çakışması gibi 409'lar
     * `detail` dışında makine okunur alanlar taşır (`kod: "PLAN_CAKISMA"`,
     * `cakismalar`); `cakisma` getter'ı yalnız durum koduna baktığı için
     * çağıran, iyimser kilit 409'unu planlama çakışmasından buradan ayırır.
     */
    readonly govde?: unknown,
  ) {
    super(message);
  }

  /** Başka biri aynı kaydı değiştirdi (iyimser kilitleme). */
  get cakisma() {
    return this.status === 409;
  }

  /** Ekran etkin şirkette kullanılamaz (403 `SIRKET_DISI`). */
  get sirketDisi() {
    return this.status === 403 && sirketDisiMi(this.govde);
  }
}

/**
 * Yapısal `detail` (`{kod, mesaj, ...}` — ör. `OFIS_DISI_ERISIM`,
 * `KIRALAMA_CAKISMA`) taşıyan hatada kullanıcıya gösterilecek metin.
 */
function yapisalMesaj(detail: unknown): string | undefined {
  if (detail && typeof detail === "object" && "mesaj" in detail) {
    const m = (detail as { mesaj?: unknown }).mesaj;
    if (typeof m === "string") return m;
  }
  return undefined;
}

/**
 * Şirket kapısı (KARARLAR 2026-11-04 §1): sunucu, etkin şirkette kullanılamayan
 * ekranın ucunu 403 `{detail: {kod: "SIRKET_DISI", mesaj}}` ile kapatır.
 * İstemci bunu tek yerde tanır: hata `sirketDisi` bayrağını taşır ve bir SAYFA
 * verisi (GET) bu yüzden gelmediyse pencereye `SIRKET_DISI_OLAYI` yayılır;
 * kabuktaki rota kapısı boş tablo ("Veri Yok") yerine "bu sayfa bu şirkette
 * kullanılamaz — şirket seçiciden değiştirin" sonucunu çizer (sızıntı S4, B-06).
 */
export const SIRKET_DISI_OLAYI = "denge:sirket-disi";

export function sirketDisiMi(govde: unknown): boolean {
  const d = (govde as { detail?: unknown } | null)?.detail;
  return !!d && typeof d === "object" && (d as { kod?: unknown }).kod === "SIRKET_DISI";
}

function sirketDisiBildir(status: number, govde: unknown, mesaj: string, yontem: string | undefined) {
  if (status !== 403 || (yontem ?? "GET").toUpperCase() !== "GET" || !sirketDisiMi(govde)) return;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<string>(SIRKET_DISI_OLAYI, { detail: mesaj }));
  }
}

async function istek<T>(yol: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(yol, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "fetch",
      ...init.headers,
    },
  });

  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    let govde: unknown;
    try {
      govde = await res.json();
      const g = govde as { detail?: unknown } | null;
      if (typeof g?.detail === "string") mesaj = g.detail;
      else if (Array.isArray(g?.detail)) mesaj = g.detail[0]?.msg ?? mesaj;
      else mesaj = yapisalMesaj(g?.detail) ?? mesaj;
    } catch {
      /* gövde JSON değil — varsayılan mesaj kalsın */
    }
    sirketDisiBildir(res.status, govde, mesaj, init.method);
    throw new ApiError(res.status, mesaj, govde);
  }

  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** Sayfalı liste: kayıtlar + sunucunun bildirdiği TOPLAM. */
export interface Sayfa<T> {
  kayitlar: T[];
  toplam: number;
}

/**
 * Liste uçları toplam kayıt sayısını `X-Toplam-Kayit` başlığında döndürür.
 * Gövde düz dizi kaldığı için eski çağıranlar bozulmaz; sayfalamaya ihtiyacı
 * olan ekran `getSayfa` kullanır.
 */
async function getSayfa<T>(yol: string): Promise<Sayfa<T>> {
  const res = await fetch(yol, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
  });
  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    let govde: unknown;
    try {
      govde = await res.json();
      const d = (govde as { detail?: unknown } | null)?.detail;
      if (typeof d === "string") mesaj = d;
      else mesaj = yapisalMesaj(d) ?? mesaj;
    } catch {
      /* gövde JSON değil */
    }
    sirketDisiBildir(res.status, govde, mesaj, "GET");
    throw new ApiError(res.status, mesaj, govde);
  }
  const kayitlar = (await res.json()) as T[];
  const baslik = res.headers.get("X-Toplam-Kayit");
  return { kayitlar, toplam: baslik ? Number(baslik) : kayitlar.length };
}

/**
 * Gövdesi liste kalan bir uç ek bilgiyi başlıkta taşıdığında (ör. tayinin
 * yetkinlik uyarıları `X-Atama-Uyarilari`, yüzde kodlu JSON dizi) kullanılır.
 */
async function putBaslikli<T>(
  yol: string,
  govde: unknown,
  baslik: string,
): Promise<{ veri: T; ek: string[] }> {
  const res = await fetch(yol, {
    method: "PUT",
    body: JSON.stringify(govde),
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
  });
  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    let g: unknown;
    try {
      g = await res.json();
      const d = (g as { detail?: unknown } | null)?.detail;
      if (typeof d === "string") mesaj = d;
      else mesaj = yapisalMesaj(d) ?? mesaj;
    } catch {
      /* gövde JSON değil */
    }
    throw new ApiError(res.status, mesaj, g);
  }
  const veri = (await res.json()) as T;
  let ek: string[] = [];
  const ham = res.headers.get(baslik);
  if (ham) {
    try {
      const cozulen: unknown = JSON.parse(decodeURIComponent(ham));
      if (Array.isArray(cozulen)) ek = cozulen.map(String);
    } catch {
      /* bozuk başlık yok sayılır */
    }
  }
  return { veri, ek };
}

export const api = {
  get: <T>(yol: string) => istek<T>(yol),
  getSayfa,
  putBaslikli,
  post: <T>(yol: string, govde?: unknown) =>
    istek<T>(yol, { method: "POST", body: JSON.stringify(govde ?? {}) }),
  patch: <T>(yol: string, govde: unknown) =>
    istek<T>(yol, { method: "PATCH", body: JSON.stringify(govde) }),
  put: <T>(yol: string, govde: unknown) =>
    istek<T>(yol, { method: "PUT", body: JSON.stringify(govde) }),
  /** Gövde isteğe bağlı (ör. plan geri alma nedeni: `DELETE .../plan {neden, not}`). */
  delete: <T>(yol: string, govde?: unknown) =>
    istek<T>(yol, {
      method: "DELETE",
      ...(govde === undefined ? {} : { body: JSON.stringify(govde) }),
    }),
};

// --- Sunucu tipleri ---------------------------------------------------------

export interface Rol {
  code: string;
  name: string;
  scope: string;
}

export interface Kullanici {
  id: number;
  full_name: string;
  username: string;
  email: string | null;
  is_active: boolean;
  mfa_enabled: boolean;
  mfa_kurulumu_gerekli?: boolean;
  role: Rol;
  permissions: string[];
  sees_cost: boolean;
  version?: number;
  /** Teknik servis Dalga 0 (TS-002/TS-007): `/api/auth/me` bunları da döndürür. */
  giris_acik?: boolean;
  parola_degismeli?: boolean;
  birimler?: string[];
  birincil_birim?: string | null;
  /** Şirket ayrımı (KARARLAR 2026-11-04 §1): etkin şirket kodu ve üyelikler. */
  aktif_sirket?: string | null;
  sirketler?: { kod: string; ad: string; birimler: string[] }[];
  /**
   * Etkin şirkette görülebilen birimler (rol testi tur 2, KARARLAR 2026-11-04
   * §7.17; sunucu `kapsam.gorunur_birimler`). Oturum dışı ya da birim üyeliği
   * olmayan satış kapsamında boş gelir — boşsa ekran eski türetmeye düşer.
   */
  gorunur_birimler?: string[];
}

export interface GirisSonucu {
  mfa_required: boolean;
  pending_token: string | null;
  user: Kullanici | null;
}
