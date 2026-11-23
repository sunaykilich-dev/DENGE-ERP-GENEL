/**
 * Telefon/bilgisayar kamerasıyla barkod/QR okuma.
 *
 * Tarayıcının `BarcodeDetector` API'si varsa (Android Chrome, masaüstü Chrome)
 * o kullanılır; yoksa (iOS Safari, Firefox) `@zxing/browser` İHTİYAÇ ANINDA
 * yüklenir (dinamik import → ayrı parça; ana paket büyümez). Desteklenenler:
 * Code128, Code39, EAN-13/8, UPC-A, ITF ve QR. Kamera HTTPS ister (localhost hariç).
 */

const ISTENEN_BICIMLER = ["code_128", "code_39", "ean_13", "ean_8", "upc_a", "itf", "qr_code"];
const ARALIK_MS = 150;

interface AlgilananKod {
  rawValue: string;
}
interface BarcodeDetectorSinifi {
  new (o?: { formats?: string[] }): { detect(kaynak: CanvasImageSource): Promise<AlgilananKod[]> };
  getSupportedFormats?: () => Promise<string[]>;
}

export class KameraHatasi extends Error {}

const KAMERA: MediaStreamConstraints = {
  video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
  audio: false,
};

function kameraDenetimi() {
  if (!window.isSecureContext) {
    throw new KameraHatasi("Kamera yalnız güvenli bağlantıda (https) açılır.");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new KameraHatasi("Bu tarayıcı kameraya erişemiyor; el okuyucu ya da elle giriş kullanın.");
  }
}

function kameraMesaji(e: unknown): Error {
  const ad = (e as { name?: string })?.name;
  if (ad === "NotAllowedError" || ad === "SecurityError") {
    return new KameraHatasi("Kamera izni verilmedi. Tarayıcı ayarlarından kamera iznini açın.");
  }
  if (ad === "NotFoundError" || ad === "OverconstrainedError") {
    return new KameraHatasi("Kamera bulunamadı.");
  }
  if (ad === "NotReadableError") {
    return new KameraHatasi("Kamera başka bir uygulama tarafından kullanılıyor.");
  }
  return e instanceof Error ? e : new KameraHatasi("Kamera açılamadı.");
}

async function yerelAlgilayici(): Promise<InstanceType<BarcodeDetectorSinifi> | null> {
  const Sinif = (window as unknown as { BarcodeDetector?: BarcodeDetectorSinifi }).BarcodeDetector;
  if (!Sinif) return null;
  try {
    const destek = (await Sinif.getSupportedFormats?.()) ?? ISTENEN_BICIMLER;
    const bicimler = ISTENEN_BICIMLER.filter((b) => destek.includes(b));
    return bicimler.length ? new Sinif({ formats: bicimler }) : null;
  } catch {
    return null;
  }
}

/** Taramayı başlatır; ilk okunan kodla `okundu` çağrılır. Dönen işlev kamerayı kapatır. */
export async function taramayiBaslat(
  video: HTMLVideoElement,
  okundu: (metin: string) => void,
): Promise<() => void> {
  kameraDenetimi();
  const algilayici = await yerelAlgilayici();
  if (algilayici) {
    let akis: MediaStream;
    try {
      akis = await navigator.mediaDevices.getUserMedia(KAMERA);
    } catch (e) {
      throw kameraMesaji(e);
    }
    video.srcObject = akis;
    video.setAttribute("playsinline", "true");
    video.muted = true;
    await video.play().catch(() => undefined);
    let bitti = false;
    let zamanlayici = 0;
    const dongu = async () => {
      if (bitti) return;
      try {
        if (video.readyState >= 2) {
          const kodlar = await algilayici.detect(video);
          const metin = kodlar.find((k) => k.rawValue?.trim())?.rawValue.trim();
          if (metin && !bitti) {
            okundu(metin);
            return;
          }
        }
      } catch {
        // Kare okunamadı: sonraki karede yeniden denenir.
      }
      zamanlayici = window.setTimeout(() => void dongu(), ARALIK_MS);
    };
    void dongu();
    return () => {
      bitti = true;
      window.clearTimeout(zamanlayici);
      akis.getTracks().forEach((t) => t.stop());
      video.srcObject = null;
    };
  }

  const { BrowserMultiFormatReader } = await import("@zxing/browser");
  const okuyucu = new BrowserMultiFormatReader(undefined, { delayBetweenScanAttempts: ARALIK_MS });
  let bitti = false;
  try {
    const denetim = await okuyucu.decodeFromConstraints(KAMERA, video, (sonuc) => {
      const metin = sonuc?.getText().trim();
      if (metin && !bitti) okundu(metin);
    });
    return () => {
      bitti = true;
      denetim.stop();
    };
  } catch (e) {
    throw kameraMesaji(e);
  }
}
