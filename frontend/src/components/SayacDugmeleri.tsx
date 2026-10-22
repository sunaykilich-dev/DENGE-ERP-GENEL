/**
 * Sayaç Düğmeleri — tek dokunuş saha akışı (TS-071…074).
 *
 * Hangi düğmenin çıkacağına SUNUCU karar verir (`izinli_dugmeler`): istemci
 * akış tablosunu kopyalamaz. Düğmeler ≥ 44 px, istek sürerken kilitli; bağlantı
 * yoksa tamamen kilitli ve "Bağlantı yok — süreyi sonra elle girin" uyarısı
 * çıkar (çevrimdışı basış biriktirilmez, K19).
 *
 * Aynı dosyada iki pencere: `UnuttumPenceresi` (gerçek bitiş + gerekçe, bant da
 * kullanır) ve `ManuelKayitPenceresi` (elle süre; Bugünüm ve iş kartı kullanır).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  BEKLEME_NEDENLERI,
  FAALIYET_ADLARI,
  ZAMAN_SORGULARI,
  servisZaman,
  sunucuSimdi,
  type AcikBolum,
  type BenimSayacim,
  type Faaliyet,
} from "../api/servisZaman";

const BUYUK = { minHeight: 44 } as const;
const DIGER_FAALIYETLER: Faaliyet[] = ["UZAKTAN", "ATOLYE", "TEST", "DIGER"];

/** Tarayıcının çevrimiçi durumu (bağlantı yoksa düğmeler kilitlenir). */
export function useCevrimici(): boolean {
  const [cevrimici, setCevrimici] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  useEffect(() => {
    const ac = () => setCevrimici(true);
    const kapa = () => setCevrimici(false);
    window.addEventListener("online", ac);
    window.addEventListener("offline", kapa);
    return () => {
      window.removeEventListener("online", ac);
      window.removeEventListener("offline", kapa);
    };
  }, []);
  return cevrimici;
}

/** Sayaç değişince bütün zaman ekranlarını tazeler. */
export function useZamanTazele() {
  const qc = useQueryClient();
  return () => {
    for (const anahtar of ZAMAN_SORGULARI) void qc.invalidateQueries({ queryKey: anahtar });
  };
}

function hataMesaji(e: Error): string {
  if (e instanceof ApiError && e.status === 409) {
    return `${e.message}`;
  }
  return e.message;
}

interface Props {
  /** Kartın işi; verilmezse yalnız açık sayaç düğmeleri çizilir (bant). */
  isId?: number;
  sayac: BenimSayacim | undefined;
  /** İş sayaç başlatmaya uygun mu (kapalı/beklemede değil, bana atanmış). */
  baslatilabilir?: boolean;
  /** Aynı ziyaretteki sonraki işler (Sonraki Cihaza Geç). */
  sonrakiIsler?: { id: number; so_no: string }[];
  /** Masaüstü "Diğer faaliyet" listesini göster. */
  digerFaaliyet?: boolean;
}

export default function SayacDugmeleri({
  isId,
  sayac,
  baslatilabilir = true,
  sonrakiIsler = [],
  digerFaaliyet = true,
}: Props) {
  const { message } = App.useApp();
  const tazele = useZamanTazele();
  const cevrimici = useCevrimici();
  const [beklemeAcik, setBeklemeAcik] = useState(false);
  const [unuttumAcik, setUnuttumAcik] = useState(false);
  const [degistirAcik, setDegistirAcik] = useState(false);
  const [sonrakiAcik, setSonrakiAcik] = useState(false);

  const islem = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => tazele(),
    onError: (e: Error) => {
      message.error(hataMesaji(e));
      // 409: sayaç başka yerde değişti / iş durumu uygun değil → ekranı tazele.
      tazele();
    },
  });
  const kilitli = islem.isPending || !cevrimici || !sayac;
  const acik = sayac?.acik_bolum ?? null;
  const dugmeler = new Set(sayac?.izinli_dugmeler ?? []);
  const yap = (fn: () => Promise<unknown>, basari?: string) =>
    islem.mutate(fn, { onSuccess: () => basari && message.success(basari) });

  if (!cevrimici) {
    return (
      <Alert
        type="warning"
        showIcon
        title="Bağlantı yok — süreyi sonra elle girin"
        description="Sayaç sunucu saatiyle çalışır; bağlantı yokken basılan düğme kaydedilmez."
      />
    );
  }

  // Açık sayaç başka işteyse bu kartta yalnız bilgi verilir.
  if (acik && isId !== undefined && acik.service_order_id !== isId) {
    return (
      <Alert
        type="info"
        showIcon
        title={
          <span>
            Sayacınız başka işte açık:{" "}
            <Link to={`/benim-islerim/${acik.service_order_id}`}>{acik.so_no}</Link> (
            {FAALIYET_ADLARI[acik.faaliyet]})
          </span>
        }
        description="Önce o sayacı bitirin ya da sonraki işe taşıyın."
      />
    );
  }

  if (!acik) {
    if (isId === undefined) return null;
    if (!baslatilabilir) {
      return (
        <Typography.Text type="secondary">
          Bu işte sayaç başlatılamaz (işe atanmamışsınız ya da iş kapalı/beklemede).
        </Typography.Text>
      );
    }
    return (
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        <Button
          type="primary"
          block
          size="large"
          style={BUYUK}
          disabled={kilitli}
          loading={islem.isPending}
          onClick={() =>
            yap(() => servisZaman.baslat({ is_id: isId, eylem: "YOLA_CIKTIM" }), "Yola çıkıldı")
          }
        >
          Yola Çıktım
        </Button>
        <Button
          block
          size="large"
          style={BUYUK}
          disabled={kilitli}
          onClick={() =>
            yap(() => servisZaman.baslat({ is_id: isId, eylem: "SAHAYA_VARDIM" }), "Sahaya varıldı")
          }
        >
          Sahaya Vardım
        </Button>
        {digerFaaliyet && (
          <Select<Faaliyet>
            size="large"
            style={{ width: "100%" }}
            placeholder="Diğer faaliyet başlat (Uzaktan/Atölye/Test…)"
            disabled={kilitli}
            value={null as unknown as Faaliyet}
            options={DIGER_FAALIYETLER.map((f) => ({ value: f, label: FAALIYET_ADLARI[f] }))}
            onChange={(f) =>
              yap(
                () => servisZaman.baslat({ is_id: isId, eylem: "DIGER", faaliyet: f }),
                `${FAALIYET_ADLARI[f]} başladı`,
              )
            }
          />
        )}
      </Space>
    );
  }

  const geriAlinabilir = dugmeler.has("GERI_AL") && sayac?.geri_alma_bitis;
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {dugmeler.has("SAHAYA_VARDIM") && (
        <Button
          type="primary"
          block
          size="large"
          style={BUYUK}
          disabled={kilitli}
          onClick={() => yap(() => servisZaman.gecis(acik, { faaliyet: "SAHA" }), "Sahaya varıldı")}
        >
          Sahaya Vardım
        </Button>
      )}
      {dugmeler.has("DEVAM") && (
        <Button
          type="primary"
          block
          size="large"
          style={BUYUK}
          disabled={kilitli}
          onClick={() => yap(() => servisZaman.devam(acik), "Devam ediliyor")}
        >
          Devam
        </Button>
      )}
      <Space.Compact block>
        {dugmeler.has("MOLA") && (
          <Button
            size="large"
            style={{ ...BUYUK, flex: 1 }}
            disabled={kilitli}
            onClick={() => yap(() => servisZaman.mola(acik), "Molaya çıkıldı")}
          >
            Mola
          </Button>
        )}
        {dugmeler.has("BEKLEME") && (
          <Button
            size="large"
            style={{ ...BUYUK, flex: 1 }}
            disabled={kilitli}
            onClick={() => setBeklemeAcik(true)}
          >
            Bekleme
          </Button>
        )}
      </Space.Compact>
      {dugmeler.has("SONRAKI_ISE_GEC") && sonrakiIsler.length > 0 && (
        <Button
          block
          size="large"
          style={BUYUK}
          disabled={kilitli}
          onClick={() => setSonrakiAcik(true)}
        >
          Sonraki Cihaza Geç
        </Button>
      )}
      {dugmeler.has("BITIR") && (
        <Button
          danger
          block
          size="large"
          style={BUYUK}
          disabled={kilitli}
          onClick={() => yap(() => servisZaman.bitir(acik), "Sayaç bitirildi")}
        >
          Bitir
        </Button>
      )}
      <Space wrap size={4}>
        {dugmeler.has("DEGISTIR") && (
          <Button type="link" size="small" disabled={kilitli} onClick={() => setDegistirAcik(true)}>
            Faaliyeti değiştir
          </Button>
        )}
        {dugmeler.has("UNUTTUM") && (
          <Button type="link" size="small" disabled={kilitli} onClick={() => setUnuttumAcik(true)}>
            Unuttum, gerçek bitişi gir
          </Button>
        )}
        {geriAlinabilir && (
          <Button
            type="link"
            size="small"
            danger
            disabled={kilitli}
            onClick={() => yap(() => servisZaman.geriAl(acik), "Sayaç geri alındı")}
          >
            Yanlış başlattım
          </Button>
        )}
      </Space>

      <BeklemePenceresi
        acik={beklemeAcik}
        onKapat={() => setBeklemeAcik(false)}
        onSec={(neden) => {
          setBeklemeAcik(false);
          yap(
            () => servisZaman.gecis(acik, { faaliyet: "BEKLEME", bekleme_nedeni: neden }),
            "Bekleme başladı",
          );
        }}
      />
      <Modal
        open={degistirAcik}
        title="Faaliyeti değiştir"
        footer={null}
        onCancel={() => setDegistirAcik(false)}
        destroyOnHidden
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          {(["YOL", "SAHA", "UZAKTAN", "ATOLYE", "TEST", "DIGER"] as Faaliyet[])
            .filter((f) => f !== acik.faaliyet)
            .map((f) => (
              <Button
                key={f}
                block
                size="large"
                style={BUYUK}
                disabled={kilitli}
                onClick={() => {
                  setDegistirAcik(false);
                  yap(() => servisZaman.gecis(acik, { faaliyet: f }), `${FAALIYET_ADLARI[f]} başladı`);
                }}
              >
                {FAALIYET_ADLARI[f]}
              </Button>
            ))}
        </Space>
      </Modal>
      <Modal
        open={sonrakiAcik}
        title="Sayacı sonraki işe taşı"
        footer={null}
        onCancel={() => setSonrakiAcik(false)}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          Bu işteki süre şimdi biter, seçtiğiniz işte aynı anda başlar. Yol süresi ilk işte kalır.
        </Typography.Paragraph>
        <Space orientation="vertical" style={{ width: "100%" }}>
          {sonrakiIsler.map((i) => (
            <Button
              key={i.id}
              block
              size="large"
              style={BUYUK}
              disabled={kilitli}
              onClick={() => {
                setSonrakiAcik(false);
                yap(
                  () =>
                    servisZaman.gecis(acik, {
                      faaliyet: acik.faaliyet === "YOL" ? "SAHA" : acik.faaliyet,
                      hedef_is_id: i.id,
                    }),
                  `Sayaç ${i.so_no} işine taşındı`,
                );
              }}
            >
              {i.so_no}
            </Button>
          ))}
        </Space>
      </Modal>
      <UnuttumPenceresi bolum={unuttumAcik ? acik : null} onKapat={() => setUnuttumAcik(false)} />
    </Space>
  );
}

function BeklemePenceresi({
  acik,
  onKapat,
  onSec,
}: {
  acik: boolean;
  onKapat: () => void;
  onSec: (neden: string) => void;
}) {
  return (
    <Modal open={acik} title="Bekleme nedeni" footer={null} onCancel={onKapat} destroyOnHidden>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Sahada beklediğiniz süre kişi-saate dahildir; işin kendisi beklemeye ALINMAZ. İşi
        beklemeye almak için iş ekranındaki "Beklet" işlemini kullanın.
      </Typography.Paragraph>
      <Space orientation="vertical" style={{ width: "100%" }}>
        {BEKLEME_NEDENLERI.filter((n) => n.kod !== "DIGER").map((n) => (
          <Button key={n.kod} block size="large" style={BUYUK} onClick={() => onSec(n.kod)}>
            {n.ad}
          </Button>
        ))}
      </Space>
    </Modal>
  );
}

/** Unutulan sayacı gerçek bitiş + gerekçeyle kapatma (KULLANICI_DUZELTMESI). */
export function UnuttumPenceresi({
  bolum,
  onKapat,
}: {
  bolum: AcikBolum | null;
  onKapat: () => void;
}) {
  const { message } = App.useApp();
  const tazele = useZamanTazele();
  const [form] = Form.useForm<{ bitis: Dayjs; gerekce: string }>();
  const kaydet = useMutation({
    mutationFn: (v: { bitis: Dayjs; gerekce: string }) =>
      servisZaman.unuttum(bolum!, v.bitis.toISOString(), v.gerekce),
    onSuccess: () => {
      message.success("Sayaç gerçek bitişle kapatıldı");
      tazele();
      onKapat();
    },
    onError: (e: Error) => {
      message.error(e.message);
      tazele();
    },
  });
  const baslangic = bolum ? dayjs(bolum.started_at) : null;
  return (
    <Modal
      open={!!bolum}
      title="Unuttum — gerçek bitişi girin"
      okText="Kapat"
      cancelText="Vazgeç"
      onCancel={onKapat}
      onOk={() => form.submit()}
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      {bolum && baslangic && (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ bitis: dayjs(sunucuSimdi()) }}
          onFinish={(v) => kaydet.mutate(v)}
        >
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            {bolum.so_no} · {FAALIYET_ADLARI[bolum.faaliyet]} ·{" "}
            {baslangic.format("DD.MM.YYYY HH:mm")} başladı. Kayıt "düzeltilmiş" olarak işaretlenir.
          </Typography.Paragraph>
          <Form.Item
            name="bitis"
            label="Gerçek bitiş"
            rules={[{ required: true, message: "Bitiş saatini seçin" }]}
          >
            <DatePicker
              showTime={{ format: "HH:mm" }}
              format="DD.MM.YYYY HH:mm"
              style={{ width: "100%" }}
              disabledDate={(d) =>
                d.isBefore(baslangic, "day") || d.isAfter(dayjs(sunucuSimdi()), "day")
              }
            />
          </Form.Item>
          <Form.Item
            name="gerekce"
            label="Gerekçe"
            rules={[{ required: true, whitespace: true, message: "Gerekçe yazın" }]}
          >
            <Input.TextArea rows={2} maxLength={300} placeholder="Örn. işi 15:00'te bitirdim, sayacı kapatmayı unuttum" />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}

/** Elle süre kaydı (kendi adına; `servis.planla` sahibi kişi seçebilir). */
export function ManuelKayitPenceresi({
  isId,
  soNo,
  acik,
  onKapat,
  kisiler,
}: {
  isId: number | null;
  soNo?: string;
  acik: boolean;
  onKapat: () => void;
  /** Verilirse kişi seçimi görünür (yalnız `servis.planla`). */
  kisiler?: { id: number; ad: string }[];
}) {
  const { message } = App.useApp();
  const tazele = useZamanTazele();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const kaydet = useMutation({
    mutationFn: (v: {
      faaliyet: Faaliyet;
      aralik: [Dayjs, Dayjs];
      bekleme_nedeni?: string;
      gerekce?: string;
      user_id?: number;
      aciklama?: string;
    }) =>
      servisZaman.manuel(isId!, {
        faaliyet: v.faaliyet,
        started_at: v.aralik[0].toISOString(),
        ended_at: v.aralik[1].toISOString(),
        bekleme_nedeni: v.faaliyet === "BEKLEME" ? v.bekleme_nedeni : undefined,
        gerekce: v.gerekce || undefined,
        user_id: v.user_id,
        aciklama: v.aciklama || undefined,
      }),
    onSuccess: () => {
      message.success("Süre kaydedildi");
      tazele();
      void qc.invalidateQueries({ queryKey: ["is-zamani", isId] });
      onKapat();
    },
    onError: (e: Error) => message.error(e.message),
  });
  const faaliyet = Form.useWatch("faaliyet", form);
  return (
    <Modal
      open={acik && isId !== null}
      title={`Elle süre gir${soNo ? ` — ${soNo}` : ""}`}
      okText="Kaydet"
      cancelText="Vazgeç"
      onCancel={onKapat}
      onOk={() => form.submit()}
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ faaliyet: "SAHA" }}
        onFinish={(v) => kaydet.mutate(v)}
      >
        {kisiler && (
          <Form.Item name="user_id" label="Kişi" extra="Boş bırakılırsa sizin adınıza girilir.">
            <Select
              allowClear
              options={kisiler.map((k) => ({ value: k.id, label: k.ad }))}
              placeholder="Kendim"
            />
          </Form.Item>
        )}
        <Form.Item name="faaliyet" label="Faaliyet" rules={[{ required: true }]}>
          <Select
            options={(Object.keys(FAALIYET_ADLARI) as Faaliyet[]).map((f) => ({
              value: f,
              label: FAALIYET_ADLARI[f],
            }))}
          />
        </Form.Item>
        {faaliyet === "BEKLEME" && (
          <Form.Item
            name="bekleme_nedeni"
            label="Bekleme nedeni"
            rules={[{ required: true, message: "Neden seçin" }]}
          >
            <Select options={BEKLEME_NEDENLERI.map((n) => ({ value: n.kod, label: n.ad }))} />
          </Form.Item>
        )}
        <Form.Item
          name="aralik"
          label="Başlangıç – bitiş"
          rules={[{ required: true, message: "Saat aralığını seçin" }]}
        >
          <DatePicker.RangePicker
            showTime={{ format: "HH:mm" }}
            format="DD.MM.YYYY HH:mm"
            style={{ width: "100%" }}
            disabledDate={(d) => d.isAfter(dayjs(sunucuSimdi()), "day")}
          />
        </Form.Item>
        <Form.Item
          name="gerekce"
          label="Gerekçe"
          extra="Bitişi 30 dakikadan eski kayıtta zorunlu."
        >
          <Input maxLength={300} />
        </Form.Item>
        <Form.Item name="aciklama" label="Yapılan iş">
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
