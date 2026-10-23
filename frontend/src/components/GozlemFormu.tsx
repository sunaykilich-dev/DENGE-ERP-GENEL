/**
 * Saha gözlemi formu ve servis işi detayındaki "Saha Gözlemleri" kartı (TS-156).
 *
 * Kurallar sunucudadır; form yalnız kolaylaştırır:
 * - Puan ve sonuç SUNUCUDA hesaplanır; formda gösterilen rozet önizlemedir.
 * - Kritik maddelerin varsayılanı YOK (seçim zorunlu); "Gözlenmedi" gerekçe ister.
 * - Servis işinden açılınca iş no ve birim kilitlidir; işe tayin edilmiş kişiler
 *   personel seçiminde önce gelir. Gözlemci oturumdaki kullanıcıdır.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Radio,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import type { ApiError } from "../api/client";
import {
  ASAMALAR,
  asamaEtiketi,
  egitimApi,
  MADDE_PUANLARI,
  SONUC_ETIKETLERI,
  SONUC_RENKLERI,
  type Gozlem,
} from "../api/egitim";
import { BIRIM_ETIKETLERI } from "../api/personel";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";

interface ServisBagi {
  soId: number;
  soNo: string;
  birim: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  servis?: ServisBagi;
  kisiId?: number;
  onKaydedildi?: (g: Gozlem) => void;
}

interface FormDegeri {
  user_id: number;
  course_id: number;
  asama: number;
  gozlem_tarihi: Dayjs;
  notlar?: string;
  aksiyon_plani?: string;
}

export function SonucRozeti({ g }: { g: Pick<Gozlem, "sonuc" | "puan" | "cancelled_at"> }) {
  if (g.cancelled_at) return <Tag>İptal</Tag>;
  const puan = g.puan == null ? "" : ` %${Number(g.puan).toLocaleString("tr-TR")}`;
  return (
    <Tag color={SONUC_RENKLERI[g.sonuc]}>
      {g.sonuc === "KRITIK" ? "KRİTİK" : `${SONUC_ETIKETLERI[g.sonuc] ?? g.sonuc}${puan}`}
    </Tag>
  );
}

export default function GozlemFormu({ open, onClose, servis, kisiId, onKaydedildi }: Props) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<FormDegeri>();
  const [arama, setArama] = useState("");
  const [puanlar, setPuanlar] = useState<Record<number, number | undefined>>({});
  const [gerekceler, setGerekceler] = useState<Record<number, string>>({});
  const [sonuc, setSonuc] = useState<{ gozlem: Gozlem; uyarilar: string[] } | null>(null);
  const kursId = Form.useWatch("course_id", form);

  const kurslar = useQuery({
    queryKey: ["egitim-kurslar", "aktif"],
    queryFn: () => egitimApi.kurslar({ aktif: true }),
    enabled: open,
  });
  const kriterler = useQuery({
    queryKey: ["egitim-kriterler", kursId],
    queryFn: () => egitimApi.kriterler(kursId),
    enabled: open && !!kursId,
  });
  const kisiler = useQuery({
    queryKey: ["egitim-kisiler", "secim", arama],
    queryFn: () => egitimApi.kisiler({ q: arama }, 50, 0),
    enabled: open,
  });
  const ekip = useQuery({
    queryKey: ["servis-ekip", servis?.soId],
    queryFn: () => teknikServisApi.ekip(servis!.soId),
    enabled: open && !!servis,
  });

  const kisiSecenekleri = useMemo(() => {
    const atanan = new Set((ekip.data ?? []).map((e) => e.user_id));
    const liste = kisiler.data?.kayitlar ?? [];
    const sirali = [...liste.filter((k) => atanan.has(k.id)), ...liste.filter((k) => !atanan.has(k.id))];
    return sirali.map((k) => ({
      value: k.id,
      label: `${k.ad}${atanan.has(k.id) ? " (bu işe tayin edilmiş)" : ""}`,
    }));
  }, [kisiler.data, ekip.data]);

  const aktifMaddeler = (kriterler.data ?? []).filter((k) => k.is_active);

  const kaydet = useMutation({
    mutationFn: (v: FormDegeri) =>
      egitimApi.gozlemKaydet({
        user_id: v.user_id,
        course_id: v.course_id,
        asama: v.asama,
        gozlem_tarihi: v.gozlem_tarihi.format("YYYY-MM-DD"),
        service_order_id: servis?.soId ?? null,
        notlar: v.notlar || null,
        aksiyon_plani: v.aksiyon_plani || null,
        puanlar: aktifMaddeler
          .filter((m) => puanlar[m.id] !== undefined)
          .map((m) => ({
            criterion_id: m.id,
            puan: puanlar[m.id]!,
            gozlenmedi_gerekcesi: puanlar[m.id] === -1 ? gerekceler[m.id] || null : null,
          })),
      }),
    onSuccess: (r) => {
      setSonuc(r);
      message.success("Gözlem kaydedildi");
      void qc.invalidateQueries({ queryKey: ["egitim-gozlemler"] });
      void qc.invalidateQueries({ queryKey: ["egitim-ozet"] });
      void qc.invalidateQueries({ queryKey: ["servis-gozlemleri"] });
      onKaydedildi?.(r.gozlem);
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const kapat = () => {
    form.resetFields();
    setPuanlar({});
    setGerekceler({});
    setSonuc(null);
    onClose();
  };

  const eksikKritik = aktifMaddeler.some((m) => m.is_critical && puanlar[m.id] === undefined);

  return (
    <Modal
      open={open}
      onCancel={kapat}
      title={servis ? `Saha gözlemi — ${servis.soNo}` : "Saha gözlemi"}
      width={720}
      okText="Kaydet"
      onOk={() => (sonuc ? kapat() : form.submit())}
      okButtonProps={{ loading: kaydet.isPending, disabled: !sonuc && eksikKritik }}
      destroyOnHidden
    >
      {sonuc ? (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text>
            Sonuç: <SonucRozeti g={sonuc.gozlem} />
          </Typography.Text>
          {sonuc.uyarilar.map((u) => (
            <Alert key={u} type="warning" showIcon title={u} />
          ))}
          {sonuc.gozlem.sonuc === "KRITIK" && (
            <Alert type="error" showIcon title="Kritik İSG uygunsuzluğu için düzeltici faaliyet açıldı." />
          )}
        </Space>
      ) : (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ asama: 0, gozlem_tarihi: dayjs(), user_id: kisiId }}
          onFinish={(v) => kaydet.mutate(v)}
        >
          {servis && (
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag>İş: {servis.soNo}</Tag>
              <Tag>Birim: {BIRIM_ETIKETLERI[servis.birim] ?? servis.birim}</Tag>
            </Space>
          )}
          <Form.Item name="user_id" label="Gözlenen personel" rules={[{ required: true, message: "Personel seçin" }]}>
            <Select
              showSearch
              filterOption={false}
              onSearch={setArama}
              options={kisiSecenekleri}
              loading={kisiler.isLoading}
              placeholder="Ad yazın"
            />
          </Form.Item>
          <Space wrap>
            <Form.Item name="course_id" label="Eğitim" rules={[{ required: true, message: "Eğitim seçin" }]}>
              <Select
                style={{ minWidth: 260 }}
                options={(kurslar.data ?? []).map((k) => ({ value: k.id, label: `${k.kod} — ${k.baslik}` }))}
                onChange={() => setPuanlar({})}
              />
            </Form.Item>
            <Form.Item name="asama" label="Aşama">
              <Select style={{ width: 130 }} options={ASAMALAR.map((a) => ({ value: a, label: asamaEtiketi(a) }))} />
            </Form.Item>
            <Form.Item name="gozlem_tarihi" label="Tarih" rules={[{ required: true }]}>
              <DatePicker format="DD.MM.YYYY" disabledDate={(d) => d.isAfter(dayjs(), "day")} />
            </Form.Item>
          </Space>
          {aktifMaddeler.length > 0 && (
            <List
              size="small"
              bordered
              header={<Typography.Text strong>Gözlem maddeleri</Typography.Text>}
              dataSource={aktifMaddeler}
              renderItem={(m) => (
                <List.Item>
                  <Space orientation="vertical" style={{ width: "100%" }} size={4}>
                    <Space wrap size={4}>
                      {m.is_critical && <Tag color="red">Kritik</Tag>}
                      <Typography.Text>{m.metin}</Typography.Text>
                    </Space>
                    <Radio.Group
                      value={puanlar[m.id]}
                      onChange={(e) => setPuanlar((p) => ({ ...p, [m.id]: e.target.value as number }))}
                      options={MADDE_PUANLARI.map((p) => ({ value: p.deger, label: p.ad }))}
                    />
                    {puanlar[m.id] === -1 && (
                      <Input
                        size="small"
                        maxLength={300}
                        placeholder="Neden gözlenmedi?"
                        value={gerekceler[m.id] ?? ""}
                        onChange={(e) => setGerekceler((g) => ({ ...g, [m.id]: e.target.value }))}
                      />
                    )}
                  </Space>
                </List.Item>
              )}
            />
          )}
          {eksikKritik && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Kritik maddelerin hepsi puanlanmalı (gözlenmediyse gerekçeyle).
            </Typography.Text>
          )}
          <Form.Item name="notlar" label="Notlar" style={{ marginTop: 12 }}>
            <Input.TextArea rows={2} maxLength={4000} />
          </Form.Item>
          <Form.Item name="aksiyon_plani" label="Aksiyon planı">
            <Input.TextArea rows={2} maxLength={4000} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}

/** Servis işi detayındaki "Saha Gözlemleri" kartı (yalnız `egitim.gor`). */
export function ServisGozlemleri({ soId, soNo, birim }: ServisBagi) {
  const { yetkili } = useAuth();
  const [acik, setAcik] = useState(false);
  const liste = useQuery({
    queryKey: ["servis-gozlemleri", soId],
    queryFn: () => egitimApi.gozlemler({ service_order_id: soId, iptaller: true }, 100, 0),
  });
  return (
    <Card
      size="small"
      title="Saha Gözlemleri"
      extra={
        yetkili("egitim.gozlem") && (
          <Button size="small" type="primary" onClick={() => setAcik(true)}>
            Saha Gözlemi Yap
          </Button>
        )
      }
    >
      {liste.data?.kayitlar.length ? (
        <List
          size="small"
          dataSource={liste.data.kayitlar}
          renderItem={(g) => (
            <List.Item>
              <Space wrap size={4}>
                <Typography.Text>{dayjs(g.gozlem_tarihi).format("DD.MM.YYYY")}</Typography.Text>
                <Typography.Text strong>{g.ad}</Typography.Text>
                <Typography.Text type="secondary">
                  {g.kurs} · {asamaEtiketi(g.asama)}
                </Typography.Text>
                <SonucRozeti g={g} />
                {g.gozlemci_ad && <Typography.Text type="secondary">Gözlemci: {g.gozlemci_ad}</Typography.Text>}
              </Space>
            </List.Item>
          )}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Bu işte saha gözlemi yok" />
      )}
      <GozlemFormu open={acik} onClose={() => setAcik(false)} servis={{ soId, soNo, birim }} />
    </Card>
  );
}
