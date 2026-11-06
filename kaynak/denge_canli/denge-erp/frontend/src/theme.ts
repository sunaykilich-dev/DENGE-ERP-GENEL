/**
 * Denge kurumsal kimliği → Ant Design tema değişkenleri.
 *
 * Değerler filo-site'taki kurumsal kimlik dosyasından birebir alındı
 * (src/styles/global.css @theme bloğu). Tek kaynak orası; burada yeniden
 * renk uydurulmaz. Aynı değerler PDF şablonlarında da kullanılacak, böylece
 * ekran ve basılı belge aynı kimliği taşır.
 *
 * Sarı (accent) BİLİNÇLİ OLARAK kullanılmıyor: kurumsal kimlikte yalnız koyu
 * zeminlerde okunabilir, ERP'nin açık zeminli ekranlarında kontrastı yetersiz.
 */
import type { ThemeConfig } from "antd";

export const marka = {
  signal: "#11417f",
  signalDeep: "#0c2f5d",
  signalWash: "#dfe6f1",
  brand2: "#3361a1",
  paper: "#f1eee8",
  paper2: "#e8e4db",
  card: "#ffffff",
  card2: "#fbf9f5",
  ink: "#141d2b",
  ink2: "#3c4657",
  ink3: "#575f6d",
  rule: "#d3ccbe",
  ruleSoft: "#e0dace",
  alarm: "#de3a11",
  alarmWash: "#f7ded6",
  verify: "#1f6b4d",
  night: "#0b1220",
} as const;

const SANS = "'Archivo Variable', 'Helvetica Neue', Helvetica, Arial, sans-serif";
export const MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace";

export const theme: ThemeConfig = {
  token: {
    colorPrimary: marka.signal,
    colorLink: marka.signal,
    colorError: marka.alarm,
    colorSuccess: marka.verify,
    colorText: marka.ink,
    colorTextSecondary: marka.ink2,
    colorTextTertiary: marka.ink3,
    colorBorder: marka.rule,
    colorBorderSecondary: marka.ruleSoft,
    colorBgLayout: marka.paper,
    colorBgContainer: marka.card,
    fontFamily: SANS,
    // Kurumsal tipografi ölçeği 16px'e çıpalı; arayüz kademesi 14px.
    fontSize: 14,
    borderRadius: 4,
    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: marka.signal,
      headerColor: "#ffffff",
      siderBg: marka.card2,
      bodyBg: marka.paper,
    },
    Menu: {
      itemSelectedBg: marka.signalWash,
      itemSelectedColor: marka.signalDeep,
    },
    Table: {
      headerBg: marka.paper2,
      headerColor: marka.ink2,
      borderColor: marka.ruleSoft,
    },
  },
};
