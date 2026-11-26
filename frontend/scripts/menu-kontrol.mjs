// Menü ↔ rota tutarlılık denetimi (KARARLAR 2026-11-04 §2). `npm run build` önce bunu çalıştırır.
//
// 1. Her menü yaprağı `src/main.tsx`'te gerçek bir rotaya gider (yolu bir <Route path> ile eşleşir).
// 2. Katalogdaki (`uygulamalar.ts` SAYFALAR) her sayfa menüde en az bir yaprakta bulunur — hiçbir sayfa kaybolmaz
//    (kişisel sayfalar — `kisisel` — kullanıcı menüsündedir; yalnız rotaları denetlenir).
// 3. Yaprak anahtarları benzersizdir (favoriler/son açılanlar bununla tutulur).
//
// menu.ts/uygulamalar.ts TypeScript + ikon bileşenleri içerir; Vite'ın getirdiği esbuild ile
// tek dosyaya paketlenip Node'da çalıştırılır (ek test aracı gerekmez).
import { build } from "esbuild";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const kok = join(dirname(fileURLToPath(import.meta.url)), "..");

const paket = await build({
  stdin: {
    contents: `
      export { MENU_AGACI, yapraklar, yolKismi } from "./src/fiori/menu.ts";
      export { SAYFALAR } from "./src/fiori/uygulamalar.ts";
    `,
    resolveDir: kok,
    loader: "ts",
  },
  bundle: true,
  platform: "node",
  format: "esm",
  jsx: "automatic",
  write: false,
  logLevel: "error",
});

const gecici = mkdtempSync(join(tmpdir(), "menu-kontrol-"));
const dosya = join(gecici, "menu.mjs");
writeFileSync(dosya, paket.outputFiles[0].text);
let modul;
try {
  modul = await import(pathToFileURL(dosya).href);
} finally {
  rmSync(gecici, { recursive: true, force: true });
}
const { MENU_AGACI, yapraklar, yolKismi, SAYFALAR } = modul;

const main = readFileSync(join(kok, "src", "main.tsx"), "utf8");
const rotalar = [...main.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]).filter((p) => p !== "*");
const rotaDesenleri = rotalar.map((p) => new RegExp(`^${p.replace(/:[^/]+/g, "[^/]+")}$`));

const hatalar = [];
const tumYapraklar = yapraklar(MENU_AGACI);

for (const { yaprak, atalar } of tumYapraklar) {
  const yol = yolKismi(yaprak.yol);
  if (!rotaDesenleri.some((d) => d.test(yol))) {
    const iz = [...atalar.map((a) => a.baslik), yaprak.baslik].join(" › ");
    hatalar.push(`Rotası olmayan menü yaprağı: ${iz} → ${yaprak.yol}`);
  }
}

const menuYollari = new Set(tumYapraklar.map(({ yaprak }) => yolKismi(yaprak.yol)));
for (const s of SAYFALAR) {
  if (s.yol.startsWith("#")) continue;
  // Kişisel sayfalar kullanıcı menüsündedir (Kabuk), sol menüde değil; rotası olmalı.
  if (s.kisisel) {
    if (!rotaDesenleri.some((d) => d.test(yolKismi(s.yol)))) hatalar.push(`Rotası olmayan kişisel sayfa: ${s.baslik} (${s.yol})`);
    continue;
  }
  if (!menuYollari.has(yolKismi(s.yol))) hatalar.push(`Menüde olmayan sayfa: ${s.baslik} (${s.yol})`);
}

const gorulen = new Set();
for (const { yaprak } of tumYapraklar) {
  if (gorulen.has(yaprak.anahtar)) hatalar.push(`Yinelenen menü anahtarı: ${yaprak.anahtar}`);
  gorulen.add(yaprak.anahtar);
}

if (hatalar.length) {
  console.error(`menu-kontrol: ${hatalar.length} sorun\n  - ${hatalar.join("\n  - ")}`);
  process.exit(1);
}
console.log(`menu-kontrol: ${tumYapraklar.length} yaprak, ${rotalar.length} rota, ${SAYFALAR.length} sayfa — tutarlı.`);
