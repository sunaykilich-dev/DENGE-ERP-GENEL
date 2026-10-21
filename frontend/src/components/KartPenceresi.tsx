import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  DatePicker,
  Divider,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Kullanici } from "../api/client";
import {
  gorevApi,
  ONCELIK_ETIKET,
  type Kart,
  type KayitTipi,
  type Kolon,
  type Pano,
} from "../api/gorevler";

/**
 * Kart penceresi — HEM yeni kart HEM düzenleme.
 *
 * Tek bir form tanımı: "yeni kart açarken sorulan alanlar" ile "sonradan
 * düzenlenebilen alanlar" ayrı yazılsaydı biri diğerinden sapardı ve kart
 * ancak açıldıktan SONRA tam doldurulabilirdi — kullanıcının şikâyeti tam
 * olarak buydu.
 *
 * Yorumlar yalnız var olan kartta görünür: henüz oluşmamış bir karta yorum
 * yazılamaz.
 */
export default function KartPenceresi({
  acik,
  kart,
  pano,
  kolonId,
  duzenleyebilir,
  onKapat,
}: {
  acik: boolean;
  /** null ise YENİ kart. */
  kart: Kart | null;
  pano: Pano | undefined;
  /** Yeni kartın açılacağı kolon. */
  kolonId?: number;
  duzenleyebilir: boolean;
  onKapat: () => void;
}) {
  const yeni = kart === null;
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  // Yorum kutusu form örneğini PAYLAŞMAZ: aynı `Form` örneğini ikinci kez
  // bağlamak `form.submit()` çağrısını onFinish'i olmayan forma yönlendirir
  // ve Kaydet sessizce hiçbir şey yapmaz.
  const [yorumMetni, setYorumMetni] = useState("");

  const kullanicilar = useQuery({
    queryKey: ["kullanicilar"],
    queryFn: () => api.get<Kullanici[]>("/api/kullanicilar"),
    // `sistem.kullanici` izni olmayanda 403 döner; kişi kutusu boş kalır ama
    // kartın geri kalanı çalışmaya devam etsin diye hata yutulur.
    retry: false,
    enabled: acik,
  });
  const tipler = useQuery({
    queryKey: ["gorev-kayit-tipleri"],
    queryFn: () => gorevApi.kayitTipleri(),
    enabled: acik,
  });
  const yorumlar = useQuery({
    queryKey: ["kart-yorumlar", kart?.id],
    queryFn: () => gorevApi.yorumlar(kart!.id),
    enabled: acik && !yeni,
  });

  useEffect(() => {
    if (!acik) return;
    setYorumMetni("");
    if (yeni) {
      form.resetFields();
      form.setFieldsValue({ oncelik: "NORMAL", column_id: kolonId });
      return;
    }
    form.setFieldsValue({
      column_id: kart.column_id,
      title: kart.title,
      description: kart.description ?? undefined,
      uyeler: kart.uyeler.map((u) => u.id),
      etiketler: kart.etiketler.map((e) => e.id),
      due_date: kart.due_date ? dayjs(kart.due_date) : undefined,
      oncelik: kart.oncelik,
      entity: kart.baglanti?.entity ?? undefined,
      entity_id: kart.baglanti?.entity_id ?? undefined,
    });
  }, [acik, kart, yeni, kolonId, form]);

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["pano-kartlar"] });
    void qc.invalidateQueries({ queryKey: ["kayit-gorevleri"] });
    void qc.invalidateQueries({ queryKey: ["panolar"] });
  };

  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      yeni ? gorevApi.kartAc(pano!.id, v) : gorevApi.kartGuncelle(kart!.id, v),
    onSuccess: () => {
      message.success(yeni ? "Kart oluşturuldu" : "Kart güncellendi");
      tazele();
      onKapat();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const sil = useMutation({
    mutationFn: () => gorevApi.kartSil(kart!.id),
    onSuccess: () => {
      message.success("Kart silindi");
      tazele();
      onKapat();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const yorumEkle = useMutation({
    mutationFn: (metin: string) => gorevApi.yorumEkle(kart!.id, metin),
    onSuccess: () => {
      setYorumMetni("");
      void qc.invalidateQueries({ queryKey: ["kart-yorumlar", kart?.id] });
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const kolonAdi = (id: number | undefined) =>
    pano?.kolonlar.find((k: Kolon) => k.id === id)?.title;

  return (
    <Drawer
      open={acik}
      onClose={onKapat}
      width={560}
      destroyOnHidden
      title={
        <Space size={6}>
          <span>{yeni ? "Yeni kart" : "Kart"}</span>
          {!yeni && kolonAdi(kart.column_id) && <Tag>{kolonAdi(kart.column_id)}</Tag>}
          {!yeni && kart.tamamlandi_at && (
            <Tag color="green">{dayjs(kart.tamamlandi_at).format("D MMM YYYY")} tamamlandı</Tag>
          )}
        </Space>
      }
      extra={
        duzenleyebilir && (
          <Space>
            {!yeni && (
              <Popconfirm
                title="Kart silinsin mi?"
                description="Yorumlarıyla birlikte kalıcı olarak silinir."
                okText="Sil"
                cancelText="Vazgeç"
                onConfirm={() => sil.mutate()}
              >
                <Button danger size="small" loading={sil.isPending}>
                  Sil
                </Button>
              </Popconfirm>
            )}
            <Button
              type="primary"
              size="small"
              loading={kaydet.isPending}
              onClick={() => form.submit()}
            >
              {yeni ? "Kart oluştur" : "Kaydet"}
            </Button>
          </Space>
        )
      }
    >
      <Form
        form={form}
        layout="vertical"
        disabled={!duzenleyebilir}
        onFinish={(v) => {
          const govde: Record<string, unknown> = {
            title: v.title,
            description: v.description || null,
            uyeler: v.uyeler ?? [],
            etiketler: v.etiketler ?? [],
            due_date: v.due_date ? dayjs(v.due_date).format("YYYY-MM-DD") : null,
            oncelik: v.oncelik ?? "NORMAL",
            // Kayıt tipi boşaltıldıysa bağlantı tamamen kalkar; yarım
            // bağlantıyı sunucu zaten reddeder.
            entity: v.entity || null,
            entity_id: v.entity ? Number(v.entity_id) || null : null,
          };
          if (yeni) govde.column_id = v.column_id;
          else govde.version = kart.version;
          kaydet.mutate(govde);
        }}
      >
        {yeni && (
          <Form.Item
            name="column_id"
            label="Kolon"
            rules={[{ required: true, message: "Kolon seçin" }]}
          >
            <Select
              options={(pano?.kolonlar ?? []).map((k) => ({ value: k.id, label: k.title }))}
            />
          </Form.Item>
        )}

        <Form.Item
          name="title"
          label="Konu başlığı"
          rules={[{ required: true, message: "Başlık girin" }]}
        >
          <Input placeholder="Ne yapılacak?" autoFocus={yeni} />
        </Form.Item>

        <Form.Item name="description" label="Açıklama">
          <Input.TextArea rows={4} placeholder="Ayrıntı, neye dikkat edilecek, hangi adımlar…" />
        </Form.Item>

        <Form.Item
          name="uyeler"
          label="İlgili kişiler"
          extra="Birden fazla kişi seçilebilir."
        >
          <Select
            mode="multiple"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Kimse seçilmedi"
            options={(kullanicilar.data ?? []).map((k) => ({ value: k.id, label: k.full_name }))}
          />
        </Form.Item>

        <Form.Item name="etiketler" label="Etiketler">
          <Select
            mode="multiple"
            allowClear
            placeholder="Etiket yok"
            optionLabelProp="label"
            options={(pano?.etiketler ?? []).map((e) => ({
              value: e.id,
              label: e.ad || e.renk,
              title: e.ad ?? undefined,
            }))}
            optionRender={(o) => {
              const e = pano?.etiketler.find((x) => x.id === o.value);
              return <Tag color={e?.renk}>{e?.ad || "(adsız)"}</Tag>;
            }}
            tagRender={(props) => {
              const e = pano?.etiketler.find((x) => x.id === props.value);
              return (
                <Tag color={e?.renk} closable={props.closable} onClose={props.onClose}>
                  {e?.ad || "(adsız)"}
                </Tag>
              );
            }}
          />
        </Form.Item>

        <Space size={12} style={{ display: "flex" }}>
          <Form.Item name="due_date" label="Termin (deadline)" style={{ width: 190 }}>
            <DatePicker style={{ width: "100%" }} format="DD.MM.YYYY" placeholder="Tarih seç" />
          </Form.Item>
          <Form.Item name="oncelik" label="Öncelik" style={{ width: 150 }}>
            <Select
              options={Object.entries(ONCELIK_ETIKET).map(([v, l]) => ({ value: v, label: l }))}
            />
          </Form.Item>
        </Space>

        <Divider style={{ margin: "4px 0 12px" }}>İlgili ERP kaydı</Divider>
        {!yeni && kart.baglanti && (
          <div style={{ marginBottom: 10 }}>
            {kart.baglanti.var ? (
              <Link to={kart.baglanti.yol}>
                <Tag color="blue">
                  {kart.baglanti.ad}: {kart.baglanti.etiket}
                </Tag>
              </Link>
            ) : (
              <Tag color="red">
                {kart.baglanti.ad}: {kart.baglanti.etiket}
              </Tag>
            )}
          </div>
        )}
        <Space size={8} style={{ display: "flex" }}>
          <Form.Item name="entity" label="Kayıt tipi" style={{ flex: 1 }}>
            <Select
              allowClear
              placeholder="Bağlantısız"
              options={(tipler.data ?? []).map((t: KayitTipi) => ({ value: t.kod, label: t.ad }))}
            />
          </Form.Item>
          <Form.Item
            name="entity_id"
            label="Kayıt no"
            style={{ width: 150 }}
            extra="Kaydın sistem numarası"
          >
            <Input inputMode="numeric" placeholder="örn. 850" />
          </Form.Item>
        </Space>
      </Form>

      {!yeni && (
        <>
          <Divider style={{ margin: "4px 0 12px" }}>
            Yorumlar {yorumlar.data?.length ? `(${yorumlar.data.length})` : ""}
          </Divider>
          <Space orientation="vertical" size={10} style={{ width: "100%" }}>
            {(yorumlar.data ?? []).map((y) => (
              <div key={y.id} style={{ fontSize: 13 }}>
                <Typography.Text strong style={{ fontSize: 12 }}>
                  {y.yazan ?? "—"}
                </Typography.Text>{" "}
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {dayjs(y.created_at).format("D MMM YYYY HH:mm")}
                </Typography.Text>
                <div style={{ whiteSpace: "pre-wrap" }}>{y.metin}</div>
              </div>
            ))}
            {yorumlar.data?.length === 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Henüz yorum yok.
              </Typography.Text>
            )}
            {duzenleyebilir && (
              <div style={{ width: "100%" }}>
                <Input.TextArea
                  rows={2}
                  placeholder="Yorum yazın…"
                  value={yorumMetni}
                  onChange={(e) => setYorumMetni(e.target.value)}
                />
                <Button
                  size="small"
                  style={{ marginTop: 8 }}
                  loading={yorumEkle.isPending}
                  disabled={!yorumMetni.trim()}
                  onClick={() => yorumEkle.mutate(yorumMetni.trim())}
                >
                  Yorum ekle
                </Button>
              </div>
            )}
          </Space>
        </>
      )}
    </Drawer>
  );
}
