/**
 * Mobil iş kartında "Sonuç Gir" akışı (rol testi B6, 2026-11-04).
 *
 * Teknisyen telefonda masaüstü Servis İşleri listesine gitmeden, TEK ekranda
 * sırayla: (1) kullanılan parça, (2) müşteri onayı/imzası, (3) sonuç. Tek
 * "Kaydet ve tamamla" düğmesi önce onayı (seçildiyse), sonra sonucu yazar.
 *
 * - Onay İSTEĞE BAĞLI kalır (sunucu sonuç için onay istemez; G1.9: fazla
 *   adım yok). Seçilmezse yalnız sonuç yazılır.
 * - İmza ek olarak yüklenir; kapanan işe ek yüklenemediği için onay sonuçtan
 *   ÖNCE yazılır. Sonuç 409 (süre kaydı eksik) dönerse onay tekrar yazılmaz.
 * - Sonuç düğmesi sunucunun `gecisler` listesinden gelir (ekran kural yazmaz);
 *   sonuç girilemiyorsa nedeni söylenir.
 * - Bütün dokunma hedefleri en az 44 px (B10). Fiyat/maliyet alanı YOK.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Radio,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { ZAMAN_SORGULARI } from "../api/servisZaman";
import {
  imzaYukle,
  ONAY_TURLERI,
  teknikServisApi,
  type OnayGirdisi,
  type UlasimBilgisi,
} from "../api/teknikServis";
import { olcuBirimiAdi, parcaApi } from "../api/yedekParca";
import { useAuth } from "../auth/AuthContext";
import EkYukleyici from "./EkYukleyici";
import UlasimPenceresi, { ulasimGerekiyor } from "./UlasimPenceresi";
import ImzaAlani, { tuvalPng } from "./ImzaAlani";
import ParcaHareketPenceresi from "./ParcaHareketPenceresi";
import { TalepPenceresi } from "./ServisParcalari";

const BUYUK = { minHeight: 44 } as const;

interface SonucFormu {
  onay_turu?: string;
  imzalayan_ad?: string;
  imzalayan_unvan?: string;
  eksik_nedeni?: string;
  form_ek_id?: number;
  sonuc: string;
  cozum_kanali: string;
  yapilan_islem: string;
  ariza_nedeni_id?: number;
  saha_seri_no?: string;
  sure_eksik_onay?: boolean;
}

export interface MobilSonucCekmecesiProps {
  isId: number;
  soNo: string;
  birim: string;
  acik: boolean;
  onKapat: () => void;
}

export default function MobilSonucCekmecesi({ isId, soNo, birim, acik, onKapat }: MobilSonucCekmecesiProps) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<SonucFormu>();
  const onayTuru = Form.useWatch("onay_turu", form);
  const [imzaBos, setImzaBos] = useState(true);
  const [onayYazildi, setOnayYazildi] = useState(false);
  const [sureEksik, setSureEksik] = useState<string | null>(null);
  const [parcaAcik, setParcaAcik] = useState(false);
  const [talepAcik, setTalepAcik] = useState(false);
  const imzaKutusu = useRef<HTMLDivElement | null>(null);

  const detay = useQuery({
    queryKey: ["servis-is", isId],
    queryFn: () => teknikServisApi.getir(isId),
    enabled: acik,
  });
  const sozluk = useQuery({
    queryKey: ["servis-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
    enabled: acik,
  });
  const arizaNedenleri = useQuery({
    queryKey: ["ariza-nedenleri", birim],
    queryFn: () => teknikServisApi.arizaNedenleri(birim),
    enabled: acik && !!birim,
  });
  const onaylar = useQuery({
    queryKey: ["servis-is-onay", isId],
    queryFn: () => teknikServisApi.onaylar(isId),
    enabled: acik,
  });
  const parcalar = useQuery({
    queryKey: ["parca", "is", isId],
    queryFn: () => parcaApi.isParcalari(isId),
    enabled: acik && yetkili("servis.gor"),
  });
  const formEkleri = useQuery({
    queryKey: ["ekler", "service_orders", isId],
    queryFn: () =>
      fetch(`/api/ekler/service_orders/${isId}`, { credentials: "same-origin" }).then(
        (r) => r.json() as Promise<{ id: number; kind: string; file_name: string }[]>,
      ),
    enabled: acik && onayTuru === "BASILI_FORM",
  });

  useEffect(() => {
    if (acik) {
      form.resetFields();
      setImzaBos(true);
      setOnayYazildi(false);
      setSureEksik(null);
    }
  }, [acik, form]);

  const tazele = () => {
    for (const k of ["servis-is", "servis-is-onay", "servis-is-gecmis", "servis-is-bekleme"]) {
      void qc.invalidateQueries({ queryKey: [k, isId] });
    }
    void qc.invalidateQueries({ queryKey: ["servis-isleri"] });
    for (const k of ZAMAN_SORGULARI) void qc.invalidateQueries({ queryKey: k });
  };

  const d = detay.data;
  const sonucGecisi = (d?.gecisler ?? []).find((g) => g.uc === "sonuc" && g.yetkili);
  const islemeAl = (d?.gecisler ?? []).find((g) => g.uc === "genel" && g.hedef === "ISLEMDE" && g.yetkili);
  const gecerliOnay = (onaylar.data ?? []).find(
    (o) => !(onaylar.data ?? []).some((x) => x.gecersiz_kilan_id === o.id),
  );
  const parcaKullanabilir = yetkili("parca.kullan") && !!parcalar.data?.acik;

  // KARARLAR 2026-11-20 §1: saha işinde ulaşım/km önce sorulur.
  const [ulasim, setUlasim] = useState<{
    bilgi: UlasimBilgisi;
    mod: "baslangic" | "bitis";
    sonra: () => void;
  } | null>(null);
  const ulasimlaIslemeAl = async () => {
    try {
      const b = await ulasimGerekiyor(isId, "baslangic");
      if (b) setUlasim({ bilgi: b, mod: "baslangic", sonra: () => durumaAl.mutate() });
      else durumaAl.mutate();
    } catch (e) {
      message.error((e as Error).message);
    }
  };
  const ulasimlaKaydet = async (v: SonucFormu) => {
    if (v.cozum_kanali === "YERINDE" && (v.sonuc === "COZULDU" || v.sonuc === "COZULEMEDI")) {
      try {
        const b = await ulasimGerekiyor(isId, "bitis");
        if (b) {
          setUlasim({ bilgi: b, mod: "bitis", sonra: () => kaydet.mutate(v) });
          return;
        }
      } catch (e) {
        message.error((e as Error).message);
        return;
      }
    }
    kaydet.mutate(v);
  };

  const durumaAl = useMutation({
    mutationFn: () => teknikServisApi.durum(isId, "ISLEMDE", d?.status),
    onSuccess: () => {
      message.success("İş işleme alındı");
      tazele();
    },
    onError: (e: Error) => {
      message.error(e.message);
      tazele();
    },
  });

  const kaydet = useMutation({
    mutationFn: async (v: SonucFormu) => {
      // 1) Müşteri onayı (seçildiyse ve bu akışta henüz yazılmadıysa).
      if (v.onay_turu && !onayYazildi) {
        let ekId: number | null = null;
        if (v.onay_turu === "IMZA") {
          const png = await tuvalPng(imzaKutusu.current);
          if (!png || imzaBos) throw new Error("Müşteri imzası çizilmedi");
          ekId = await imzaYukle(isId, png);
        } else if (v.onay_turu === "BASILI_FORM") {
          ekId = v.form_ek_id ?? null;
        }
        const govde: OnayGirdisi = {
          tur: v.onay_turu,
          imzalayan_ad: v.imzalayan_ad?.trim() || null,
          imzalayan_unvan: v.imzalayan_unvan?.trim() || null,
          eksik_nedeni: v.eksik_nedeni?.trim() || null,
          ek_id: ekId,
        };
        await teknikServisApi.onayAl(isId, govde);
        setOnayYazildi(true);
      }
      // 2) Sonuç.
      return teknikServisApi.sonuc(isId, {
        sonuc: v.sonuc,
        cozum_kanali: v.cozum_kanali,
        yapilan_islem: v.yapilan_islem.trim(),
        ariza_nedeni_id: v.ariza_nedeni_id ?? null,
        saha_seri_no: v.saha_seri_no?.trim() || null,
        sure_eksik_onay: !!v.sure_eksik_onay,
      });
    },
    onSuccess: () => {
      message.success(`${soNo} tamamlandı`);
      tazele();
      onKapat();
    },
    onError: (e: Error) => {
      tazele();
      // TS-076: süre kaydı eksik/kısmi işte tamamlama ayrıca onay ister.
      if (e instanceof ApiError && e.status === 409 && /süre kaydı/i.test(e.message)) {
        setSureEksik(e.message);
        return;
      }
      message.error(e.message);
    },
  });

  const bolumBasligi = (no: number, metin: string) => (
    <Typography.Title level={5} style={{ margin: "8px 0" }}>
      {no}. {metin}
    </Typography.Title>
  );

  return (
    <Drawer
      open={acik}
      onClose={onKapat}
      placement="right"
      width="100%"
      title={`Sonuç gir · ${soNo}`}
      destroyOnHidden
      styles={{ body: { paddingBottom: 96 } }}
      footer={
        <Space orientation="vertical" style={{ width: "100%" }} size={8}>
          <Button
            type="primary"
            block
            size="large"
            style={{ minHeight: 48 }}
            disabled={!sonucGecisi}
            loading={kaydet.isPending}
            onClick={() => form.submit()}
          >
            Kaydet ve tamamla
          </Button>
          <Button block size="large" style={BUYUK} onClick={onKapat}>
            Vazgeç
          </Button>
        </Space>
      }
    >
      {detay.isLoading ? null : !d ? (
        <Empty description={(detay.error as Error | null)?.message ?? "İş bulunamadı"} />
      ) : (
        <Form form={form} layout="vertical" onFinish={(v) => void ulasimlaKaydet(v)} requiredMark="optional">
          {!sonucGecisi && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              title="Bu iş şu durumda tamamlanamaz"
              description={
                islemeAl
                  ? "Önce sayacı bitirin ya da işi işleme alın; sonra sonucu kaydedin."
                  : "Sonuç girmek için işin işlemde olması ve sizin bu işe tayin edilmiş olmanız gerekir."
              }
              action={
                islemeAl ? (
                  <Button style={BUYUK} loading={durumaAl.isPending} onClick={() => void ulasimlaIslemeAl()}>
                    İşleme al
                  </Button>
                ) : undefined
              }
            />
          )}

          {/* 1) Kullanılan parça */}
          {bolumBasligi(1, "Kullanılan parça")}
          {parcalar.data && parcalar.data.ozet.length > 0 ? (
            <List
              size="small"
              dataSource={parcalar.data.ozet}
              rowKey="product_id"
              renderItem={(o) => (
                <List.Item style={{ paddingInline: 0 }}>
                  <span style={{ overflowWrap: "anywhere" }}>
                    {o.kod} — {o.ad}
                  </span>
                  <Typography.Text strong>
                    {o.net} {olcuBirimiAdi(o.birim)}
                  </Typography.Text>
                </List.Item>
              )}
            />
          ) : (
            <Typography.Paragraph type="secondary">Bu işte kullanılan parça yok.</Typography.Paragraph>
          )}
          {(parcalar.data?.talepler ?? []).some((t) => t.durum === "ACIK") && (
            <Typography.Paragraph type="secondary">
              Açık parça talebi var; ayrıntısı iş ayrıntısındaki "Parçalar" sekmesinde.
            </Typography.Paragraph>
          )}
          {parcaKullanabilir && (
            <Space.Compact block style={{ marginBottom: 8 }}>
              <Button size="large" style={{ ...BUYUK, flex: 1 }} onClick={() => setParcaAcik(true)}>
                Parça kullan
              </Button>
              <Button size="large" style={{ ...BUYUK, flex: 1 }} onClick={() => setTalepAcik(true)}>
                Parça talep et
              </Button>
            </Space.Compact>
          )}

          {/* 2) Müşteri onayı */}
          {bolumBasligi(2, "Müşteri onayı")}
          {gecerliOnay && (
            <Alert
              type="success"
              showIcon
              style={{ marginBottom: 8 }}
              title={`Geçerli onay var: ${ONAY_TURLERI.find((t) => t.kod === gecerliOnay.tur)?.ad ?? "Onay"}`}
              description={
                [gecerliOnay.imzalayan_ad, gecerliOnay.eksik_nedeni].filter(Boolean).join(" · ") ||
                "Yeni onay alırsanız öncekinin yerine geçer."
              }
            />
          )}
          {onayYazildi ? (
            <Alert type="success" showIcon style={{ marginBottom: 8 }} title="Onay kaydedildi" />
          ) : (
            <>
              <Form.Item
                name="onay_turu"
                label="Onay biçimi"
                extra={gecerliOnay ? "Boş bırakırsanız mevcut onay geçerli kalır." : "Boş bırakılabilir."}
              >
                <Radio.Group style={{ width: "100%" }}>
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    {ONAY_TURLERI.map((t) => (
                      <Radio key={t.kod} value={t.kod} style={{ minHeight: 44, alignItems: "center" }}>
                        {t.ad}
                      </Radio>
                    ))}
                  </Space>
                </Radio.Group>
              </Form.Item>
              {onayTuru && (
                <Button
                  type="link"
                  style={{ ...BUYUK, paddingInline: 0 }}
                  onClick={() => form.setFieldValue("onay_turu", undefined)}
                >
                  Onay biçimini temizle
                </Button>
              )}
              {(onayTuru === "IMZA" || onayTuru === "SOZLU" || onayTuru === "BASILI_FORM") && (
                <>
                  <Form.Item
                    name="imzalayan_ad"
                    label="Onaylayan"
                    rules={
                      onayTuru === "BASILI_FORM"
                        ? []
                        : [{ required: true, whitespace: true, message: "Ad zorunlu" }]
                    }
                  >
                    <Input size="large" maxLength={120} />
                  </Form.Item>
                  <Form.Item name="imzalayan_unvan" label="Unvan">
                    <Input size="large" maxLength={80} />
                  </Form.Item>
                </>
              )}
              {onayTuru === "IMZA" && (
                <div ref={imzaKutusu}>
                  <Form.Item label="İmza">
                    <ImzaAlani onDegisti={setImzaBos} />
                  </Form.Item>
                </div>
              )}
              {onayTuru === "BASILI_FORM" && (
                <>
                  <EkYukleyici
                    entity="service_orders"
                    entityId={isId}
                    kind="SERVIS_FORMU"
                    baslik="İmzalı servis formu"
                    aciklama="Formun fotoğrafını çekip yükleyin, sonra aşağıdan seçin."
                    yazabilir={yetkili("servis.yaz")}
                    accept="image/*,application/pdf"
                    capture="environment"
                    buyukDugme
                  />
                  <Form.Item
                    name="form_ek_id"
                    label="İmzalı formun fotoğrafı"
                    style={{ marginTop: 8 }}
                    rules={[{ required: true, message: "Formun ekini seçin" }]}
                  >
                    <Select
                      size="large"
                      loading={formEkleri.isFetching}
                      options={(formEkleri.data ?? [])
                        .filter((e) => e.kind === "SERVIS_FORMU")
                        .map((e) => ({ value: e.id, label: e.file_name }))}
                    />
                  </Form.Item>
                </>
              )}
              {onayTuru === "ALINAMADI" && (
                <Form.Item
                  name="eksik_nedeni"
                  label="Neden alınamadı?"
                  rules={[{ required: true, whitespace: true, message: "Neden zorunlu" }]}
                >
                  <Input.TextArea rows={2} maxLength={300} />
                </Form.Item>
              )}
            </>
          )}

          {/* 3) Sonuç */}
          {bolumBasligi(3, "Sonuç")}
          <Form.Item name="sonuc" label="Sonuç" rules={[{ required: true, message: "Sonuç seçin" }]}>
            <Select
              size="large"
              loading={sozluk.isLoading}
              options={(sozluk.data?.sonuclar ?? []).map((s) => ({ value: s.kod, label: s.ad }))}
            />
          </Form.Item>
          <Form.Item name="cozum_kanali" label="Çözüm kanalı" rules={[{ required: true, message: "Kanal seçin" }]}>
            <Select
              size="large"
              loading={sozluk.isLoading}
              options={(sozluk.data?.cozum_kanallari ?? []).map((s) => ({ value: s.kod, label: s.ad }))}
            />
          </Form.Item>
          <Form.Item
            name="yapilan_islem"
            label="Yapılan işlem"
            rules={[{ required: true, whitespace: true, message: "Yapılan işlemi yazın" }]}
          >
            <Input.TextArea rows={3} maxLength={4000} />
          </Form.Item>
          <Form.Item name="ariza_nedeni_id" label="Arıza nedeni">
            <Select
              size="large"
              allowClear
              loading={arizaNedenleri.isFetching}
              options={(arizaNedenleri.data ?? [])
                .filter((n) => n.is_active)
                .map((n) => ({ value: n.id, label: n.ad }))}
            />
          </Form.Item>
          <Form.Item name="saha_seri_no" label="Sahada görülen seri (farklıysa)">
            <Input size="large" maxLength={200} />
          </Form.Item>
          {sureEksik && (
            <>
              <Alert type="warning" showIcon title={sureEksik} style={{ marginBottom: 8 }} />
              <Form.Item
                name="sure_eksik_onay"
                valuePropName="checked"
                rules={[
                  {
                    validator: (_, x) =>
                      x ? Promise.resolve() : Promise.reject(new Error("Tamamlamak için onaylayın")),
                  },
                ]}
              >
                <Checkbox style={{ minHeight: 44, alignItems: "center" }}>
                  Süre kaydı eksik olduğunu biliyorum, yine de tamamla
                </Checkbox>
              </Form.Item>
            </>
          )}
          {d.sonuc && <Tag color="green">Bu işin sonucu zaten girilmiş</Tag>}
        </Form>
      )}
      <ParcaHareketPenceresi
        tur={parcaAcik ? "CIKIS" : null}
        onKapat={() => setParcaAcik(false)}
        soId={isId}
        soNo={soNo}
        birim={birim}
      />
      <TalepPenceresi acik={talepAcik} soId={isId} birim={birim} onKapat={() => setTalepAcik(false)} />
      <UlasimPenceresi
        isId={isId}
        birim={birim}
        bilgi={ulasim?.bilgi ?? null}
        mod={ulasim?.mod ?? "baslangic"}
        onKapat={() => setUlasim(null)}
        onTamam={() => {
          const sonra = ulasim?.sonra;
          setUlasim(null);
          sonra?.();
        }}
      />
    </Drawer>
  );
}
