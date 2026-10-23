/**
 * Ant Design tema değişkenleri — SAP Fiori "Quartz Light" görünümü.
 *
 * Kullanıcının şirkette her gün kullandığı SAP Fiori ekranlarına benzesin
 * diye (analiz/FIORI_TASARIM_REHBERI.md §4) uygulama kabuğu ve tüm AntD
 * bileşenleri Fiori renk ve yazı ölçüsüne çekildi: açık gri sayfa, beyaz
 * içerik kutuları, Fiori mavisi eylem rengi, 14 px Arial ("72" yazı tipi
 * kurulu değilse). Mobilite ekranları da otomatik olarak bu temayı alır.
 *
 * `marka` (Denge kurumsal kimliği) KALDIRILMADI: giriş ekranı, teklif formu
 * ve müşteriye giden teklif sayfası basılı belgeyle aynı kimliği taşır.
 */
import type { ThemeConfig } from "antd";

/** Denge kurumsal kimliği (filo-site global.css @theme bloğu). Belge/teklif içindir. */
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

/** SAP Fiori Quartz Light paleti (rehber §4). Kabuk ve launchpad bunu kullanır. */
export const fiori = {
  /** Ana eylem / bağlantı rengi. */
  mavi: "#0a6ed1",
  /** Vurgulu metin, üzerine gelinmiş bağlantı. */
  maviKoyu: "#0854a0",
  /** Seçili satır / seçili menü zemini. */
  maviZemin: "#e5f0fa",
  maviZeminKoyu: "#d8e9f8",
  kirmizi: "#bb0000",
  yesil: "#107e3e",
  turuncu: "#e9730c",
  /** Sayfa zemini. */
  sayfa: "#f7f7f7",
  kutu: "#ffffff",
  kenar: "#e5e5e5",
  kenarKoyu: "#c6c6c6",
  /** Alan (input) kenarı. */
  alanKenari: "#89919a",
  metin: "#32363a",
  metinIkincil: "#6a6d70",
  metinUcuncul: "#89919a",
  /** Kutucuk ve kabuk ikonlarının gri-mavisi. */
  ikon: "#556b82",
  /** Liste raporundaki numara rozeti (sarı vurgu). */
  sariRozet: "#ffeb3b",
} as const;

export const FIORI_FONT = '"72", "72full", Arial, Helvetica, sans-serif';
export const MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace";

export const theme: ThemeConfig = {
  token: {
    colorPrimary: fiori.mavi,
    colorInfo: fiori.mavi,
    colorLink: fiori.mavi,
    colorLinkHover: fiori.maviKoyu,
    colorLinkActive: fiori.maviKoyu,
    colorError: fiori.kirmizi,
    colorSuccess: fiori.yesil,
    colorWarning: fiori.turuncu,
    colorText: fiori.metin,
    colorTextHeading: fiori.metin,
    colorTextSecondary: fiori.metinIkincil,
    colorTextTertiary: fiori.metinUcuncul,
    colorBorder: fiori.kenarKoyu,
    colorBorderSecondary: fiori.kenar,
    colorSplit: fiori.kenar,
    colorBgLayout: fiori.sayfa,
    colorBgContainer: fiori.kutu,
    fontFamily: FIORI_FONT,
    fontSize: 14,
    fontSizeHeading4: 18,
    fontSizeHeading5: 16,
    // Düğme 4 px; kart/kutucuk 8 px (rehber §4).
    borderRadius: 4,
    borderRadiusLG: 8,
    borderRadiusSM: 4,
    controlOutline: "rgba(10, 110, 209, 0.2)",
    boxShadowTertiary: "0 0 0 1px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.06)",
    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: fiori.kutu,
      headerColor: fiori.metin,
      headerHeight: 52,
      headerPadding: "0 16px",
      bodyBg: fiori.sayfa,
      siderBg: fiori.kutu,
    },
    Menu: {
      itemSelectedBg: fiori.maviZemin,
      itemSelectedColor: fiori.maviKoyu,
      itemHoverBg: "#f5f5f5",
    },
    Button: {
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
      // Fiori varsayılan düğmesi: beyaz zemin, mavi yazı ve kenar.
      defaultColor: fiori.mavi,
      defaultBorderColor: fiori.mavi,
      defaultHoverBg: "#ebf5fe",
      defaultHoverColor: fiori.mavi,
      defaultHoverBorderColor: fiori.mavi,
      defaultActiveBg: fiori.maviZemin,
      defaultActiveColor: fiori.maviKoyu,
      defaultActiveBorderColor: fiori.maviKoyu,
      // Saydam (text) düğme: Fiori "transparent" düğmesi gibi mavi.
      textTextColor: fiori.mavi,
      textTextHoverColor: fiori.maviKoyu,
      textTextActiveColor: fiori.maviKoyu,
      textHoverBg: "#ebf5fe",
      fontWeight: 400,
    },
    Table: {
      headerBg: fiori.kutu,
      headerColor: fiori.metinIkincil,
      headerSplitColor: "transparent",
      headerBorderRadius: 0,
      borderColor: fiori.kenar,
      rowHoverBg: "#f5f5f5",
      rowSelectedBg: fiori.maviZemin,
      rowSelectedHoverBg: fiori.maviZeminKoyu,
      headerSortActiveBg: "#f5f5f5",
      headerSortHoverBg: "#f5f5f5",
      bodySortBg: "transparent",
      cellPaddingBlock: 10,
      cellPaddingBlockSM: 6,
    },
    Tabs: {
      itemColor: fiori.metin,
      itemSelectedColor: fiori.mavi,
      itemHoverColor: fiori.maviKoyu,
      inkBarColor: fiori.mavi,
      titleFontSize: 14,
    },
    Card: {
      headerFontSize: 16,
      headerBg: fiori.kutu,
    },
    Input: {
      hoverBorderColor: fiori.mavi,
      activeBorderColor: fiori.mavi,
    },
    Select: {
      optionSelectedBg: fiori.maviZemin,
    },
    Modal: {
      titleFontSize: 16,
    },
    Drawer: {
      footerPaddingBlock: 8,
    },
    Segmented: {
      itemSelectedColor: fiori.maviKoyu,
    },
    Badge: {
      dotSize: 8,
    },
  },
};
