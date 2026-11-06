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
  ) {
    super(message);
  }

  /** Başka biri aynı kaydı değiştirdi (iyimser kilitleme). */
  get cakisma() {
    return this.status === 409;
  }
}

async function istek<T>(yol: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(yol, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "fetch",
      ...(init.headers ?? {}),
    },
  });

  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    try {
      const govde = await res.json();
      if (typeof govde?.detail === "string") mesaj = govde.detail;
      else if (Array.isArray(govde?.detail)) mesaj = govde.detail[0]?.msg ?? mesaj;
    } catch {
      /* gövde JSON değil — varsayılan mesaj kalsın */
    }
    throw new ApiError(res.status, mesaj);
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
    try {
      const govde = await res.json();
      if (typeof govde?.detail === "string") mesaj = govde.detail;
    } catch {
      /* gövde JSON değil */
    }
    throw new ApiError(res.status, mesaj);
  }
  const kayitlar = (await res.json()) as T[];
  const baslik = res.headers.get("X-Toplam-Kayit");
  return { kayitlar, toplam: baslik ? Number(baslik) : kayitlar.length };
}

export const api = {
  get: <T>(yol: string) => istek<T>(yol),
  getSayfa,
  post: <T>(yol: string, govde?: unknown) =>
    istek<T>(yol, { method: "POST", body: JSON.stringify(govde ?? {}) }),
  patch: <T>(yol: string, govde: unknown) =>
    istek<T>(yol, { method: "PATCH", body: JSON.stringify(govde) }),
  put: <T>(yol: string, govde: unknown) =>
    istek<T>(yol, { method: "PUT", body: JSON.stringify(govde) }),
  delete: <T>(yol: string) => istek<T>(yol, { method: "DELETE" }),
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
}

export interface GirisSonucu {
  mfa_required: boolean;
  pending_token: string | null;
  user: Kullanici | null;
}
