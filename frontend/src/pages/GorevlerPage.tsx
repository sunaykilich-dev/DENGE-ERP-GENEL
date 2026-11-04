import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";

import { baglantiErisimYok, gorevApi, ONCELIK_ETIKET, ONCELIK_RENK, type Kart } from "../api/gorevler";
import { useAuth } from "../auth/AuthContext";
import EtiketYonetimi from "../components/EtiketYonetimi";
import KartPenceresi from "../components/KartPenceresi";

/**
 * Görev panosu (kanban).
 *
 * Sürükle–bırak tarayıcının kendi HTML5 DnD'si ile yapılır; bunun için
 * kütüphane eklenmedi. Kolon başına kart sayısı onlarla ölçülüyor, yerleşim
 * basit ve dikey liste — bir bağımlılığın getireceği paket boyutu ve sürüm
 * bakımı bu kazanca değmiyor. Sürükleyemeyen için kartın içinden kolon
 * DEĞİŞTİRİLEBİLİR olmalı; klavyeyle çalışanın tek yolu o (şu an kart
 * detayındaki "Kolon" seçimi).
 */
export default function GorevlerPage() {
  const { yetkili } = useAuth();
  const duzenleyebilir = yetkili("gorev.yaz");
  const qc = useQueryClient();
  const { message } = App.useApp();

  const [panoId, setPanoId] = useState<number>();
  const [acikKart, setAcikKart] = useState<Kart | null>(null);
  // Tam alanlı "Yeni kart" penceresi; hangi kolona açılacağını taşır.
  const [yeniKartKolonu, setYeniKartKolonu] = useState<number>();
  const [yeniPano, setYeniPano] = useState(false);
  const [yeniKolon, setYeniKolon] = useState(false);
  const [etiketler, setEtiketler] = useState(false);
  // Arşivlenen pano listeden kalkıyordu ve geri getirmenin YOLU YOKTU:
  // arşiv tek yönlü bir kapıya dönüşmüştü.
  const [arsiviGoster, setArsiviGoster] = useState(false);
  const [surukle, setSurukle] = useState<number | null>(null);
  const [hedef, setHedef] = useState<{ kolon: number; sira: number } | null>(null);
  const [panoForm] = Form.useForm();
  const [kolonForm] = Form.useForm();
  const [hizli, setHizli] = useState<Record<number, string>>({});

  const panolar = useQuery({
    queryKey: ["panolar", arsiviGoster],
    queryFn: () => gorevApi.panolar(arsiviGoster),
  });
  const pano = useMemo(
    () => (panolar.data ?? []).find((p) => p.id === panoId),
    [panolar.data, panoId],
  );
  const kartlar = useQuery({
    queryKey: ["pano-kartlar", panoId],
    queryFn: () => gorevApi.kartlar(panoId!),
    enabled: Boolean(panoId),
  });

  // YALNIZ seçim boşken ilk panoyu seçer. "Seçili pano listede yoksa ilkine
  // dön" demek YANLIŞTI: yeni pano açıldığında `setPanoId(yeni)` ile liste
  // tazelemesi yarışıyor, eski listeyle çalışan efekt seçimi ilk panoya geri
  // alıyordu. Sonuç sessiz ve tehlikeliydi — ardından basılan "Sil" düğmesi
  // BAŞKA panoyu siliyordu. Pano listeden düştüğü her yerde seçim zaten
  // ELLE temizleniyor (silme, arşivleme, arşivi gizleme).
  useEffect(() => {
    if (!panoId && panolar.data?.length) setPanoId(panolar.data[0].id);
  }, [panolar.data, panoId]);

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["pano-kartlar", panoId] });
    void qc.invalidateQueries({ queryKey: ["panolar"] });
  };

  const panoAc = useMutation({
    mutationFn: (v: { title: string; description?: string }) => gorevApi.panoAc(v),
    onSuccess: (p) => {
      message.success("Pano açıldı");
      setYeniPano(false);
      panoForm.resetFields();
      setPanoId(p.id);
      void qc.invalidateQueries({ queryKey: ["panolar"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const panoArsivle = useMutation({
    mutationFn: (arsivlendi: boolean) => gorevApi.panoGuncelle(panoId!, { arsivlendi }),
    onSuccess: (_d, arsivlendi) => {
      message.success(arsivlendi ? "Pano arşivlendi" : "Pano arşivden çıkarıldı");
      if (arsivlendi && !arsiviGoster) setPanoId(undefined);
      void qc.invalidateQueries({ queryKey: ["panolar"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const panoSil = useMutation({
    mutationFn: () => gorevApi.panoSil(panoId!),
    onSuccess: () => {
      message.success("Pano silindi");
      setPanoId(undefined);
      void qc.invalidateQueries({ queryKey: ["panolar"] });
    },
    // Kartlı pano sunucuda 409 ile reddedilir; mesaj ne yapılacağını söyler.
    onError: (e: Error) => message.error(e.message),
  });

  const kolonEkle = useMutation({
    mutationFn: (v: { title: string }) => gorevApi.kolonEkle(panoId!, v),
    onSuccess: () => {
      setYeniKolon(false);
      kolonForm.resetFields();
      void qc.invalidateQueries({ queryKey: ["panolar"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const kolonSil = useMutation({
    mutationFn: (id: number) => gorevApi.kolonSil(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["panolar"] }),
    onError: (e: Error) => message.error(e.message),
  });

  const kartAc = useMutation({
    mutationFn: (v: { column_id: number; title: string }) => gorevApi.kartAc(panoId!, v),
    onSuccess: () => tazele(),
    onError: (e: Error) => message.error(e.message),
  });

  const kartTasi = useMutation({
    mutationFn: (v: { id: number; kolon: number; sira: number }) =>
      gorevApi.kartTasi(v.id, v.kolon, v.sira),
    onSuccess: () => tazele(),
    onError: (e: Error) => {
      message.error(e.message);
      tazele();
    },
  });

  const kolonKartlari = (kolonId: number) =>
    (kartlar.data ?? []).filter((k) => k.column_id === kolonId).sort((a, b) => a.sira - b.sira);

  const birak = (kolonId: number, sira: number) => {
    if (surukle === null) return;
    kartTasi.mutate({ id: surukle, kolon: kolonId, sira });
    setSurukle(null);
    setHedef(null);
  };

  if (panolar.isLoading) return <Card loading />;

  if (!panolar.data?.length) {
    return (
      <Card title="Görevler">
        <Empty
          description={
            duzenleyebilir
              ? "Henüz pano yok. İlk panoyu açın — kolonları hazır gelir."
              : "Henüz pano yok."
          }
        >
          {duzenleyebilir && (
            <Button type="primary" onClick={() => setYeniPano(true)}>
              Yeni pano
            </Button>
          )}
        </Empty>
        <PanoModal
          acik={yeniPano}
          form={panoForm}
          yukleniyor={panoAc.isPending}
          onKapat={() => setYeniPano(false)}
          onKaydet={(v) => panoAc.mutate(v)}
        />
      </Card>
    );
  }

  return (
    <Card
      title={
        <Space size={10} wrap>
          <span>Görevler</span>
          <Segmented
            value={panoId}
            onChange={(v) => setPanoId(v as number)}
            options={(panolar.data ?? []).map((p) => ({
              value: p.id,
              label: p.arsivlendi
                ? `${p.title} (${p.kart_sayisi}) · arşiv`
                : `${p.title} (${p.kart_sayisi})`,
            }))}
          />
          <Button
            size="small"
            type={arsiviGoster ? "primary" : "default"}
            onClick={() => {
              // Arşiv gizlenirken arşivli bir pano seçiliyse seçim listede
              // olmayan bir panoya işaret ederdi.
              if (arsiviGoster && pano?.arsivlendi) setPanoId(undefined);
              setArsiviGoster((o) => !o);
            }}
          >
            {arsiviGoster ? "Arşivi gizle" : "Arşivi göster"}
          </Button>
        </Space>
      }
      extra={
        duzenleyebilir && (
          <Space>
            <Button size="small" onClick={() => setYeniKolon(true)} disabled={!panoId}>
              Kolon ekle
            </Button>
            <Button size="small" onClick={() => setEtiketler(true)} disabled={!panoId}>
              Etiketler
            </Button>
            {pano?.arsivlendi ? (
              <Button
                size="small"
                loading={panoArsivle.isPending}
                onClick={() => panoArsivle.mutate(false)}
              >
                Arşivden çıkar
              </Button>
            ) : (
              <Popconfirm
                title="Pano arşivlensin mi?"
                description="Listeden kalkar; kartları ve geçmişi durur, geri alınabilir."
                okText="Arşivle"
                cancelText="Vazgeç"
                onConfirm={() => panoArsivle.mutate(true)}
              >
                <Button size="small" disabled={!panoId}>
                  Arşivle
                </Button>
              </Popconfirm>
            )}
            <Tooltip
              title={
                pano && pano.kart_sayisi > 0
                  ? `Panoda ${pano.kart_sayisi} kart var. Silmek o işlerin geçmişini de siler — arşivleyin ya da kartları taşıyın.`
                  : undefined
              }
            >
              <Popconfirm
                title="Pano kalıcı olarak silinsin mi?"
                description="Geri alınamaz. Saklamak istiyorsanız arşivleyin."
                okText="Sil"
                okButtonProps={{ danger: true }}
                cancelText="Vazgeç"
                onConfirm={() => panoSil.mutate()}
                disabled={!panoId || (pano?.kart_sayisi ?? 0) > 0}
              >
                <Button
                  size="small"
                  danger
                  loading={panoSil.isPending}
                  disabled={!panoId || (pano?.kart_sayisi ?? 0) > 0}
                >
                  Sil
                </Button>
              </Popconfirm>
            </Tooltip>
            <Button type="primary" size="small" onClick={() => setYeniPano(true)}>
              Yeni pano
            </Button>
          </Space>
        )
      }
      styles={{ body: { overflowX: "auto" } }}
    >
      {pano?.description && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          {pano.description}
        </Typography.Paragraph>
      )}

      {pano && pano.kolonlar.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="Bu panoda kolon yok — kart açılamaz."
          style={{ margin: "24px 0" }}
        >
          {duzenleyebilir && (
            <Button type="primary" onClick={() => setYeniKolon(true)}>
              İlk kolonu ekle
            </Button>
          )}
        </Empty>
      )}

      <div style={{ display: "flex", gap: 12, alignItems: "flex-start", minHeight: 320 }}>
        {(pano?.kolonlar ?? []).map((kolon) => {
          const icerik = kolonKartlari(kolon.id);
          const asildi = kolon.wip_limit != null && icerik.length > kolon.wip_limit;
          return (
            <div
              key={kolon.id}
              onDragOver={(e) => {
                e.preventDefault();
                setHedef({ kolon: kolon.id, sira: icerik.length });
              }}
              onDrop={() => birak(kolon.id, icerik.length)}
              style={{
                width: 270,
                flex: "0 0 270px",
                background: "var(--kolon-zemin, #f5f4f0)",
                borderRadius: 8,
                padding: 8,
                outline:
                  hedef?.kolon === kolon.id && surukle !== null ? "2px dashed #11417F" : "none",
              }}
            >
              <Space style={{ width: "100%", justifyContent: "space-between" }} size={4}>
                <Space size={4}>
                  <Typography.Text strong style={{ fontSize: 13 }}>
                    {kolon.title}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {icerik.length}
                    {kolon.wip_limit != null && ` / ${kolon.wip_limit}`}
                  </Typography.Text>
                  {kolon.bitis_mi && <Tag color="green">bitiş</Tag>}
                </Space>
                <Space size={0}>
                  {duzenleyebilir && (
                    <Button
                      size="small"
                      type="text"
                      onClick={() => setYeniKartKolonu(kolon.id)}
                      title="Tüm alanlarla yeni kart"
                    >
                      <PlusOutlined />
                    </Button>
                  )}
                  {duzenleyebilir && icerik.length === 0 && (
                    <Button
                      size="small"
                      type="text"
                      danger
                      onClick={() => kolonSil.mutate(kolon.id)}
                      title="Kolonu sil"
                    >
                      ×
                    </Button>
                  )}
                </Space>
              </Space>
              {asildi && (
                <Tag color="orange" style={{ marginTop: 6 }}>
                  iş yığılıyor — sınır {kolon.wip_limit}
                </Tag>
              )}

              <Space orientation="vertical" size={6} style={{ width: "100%", marginTop: 8 }}>
                {icerik.map((kart, i) => (
                  <div
                    key={kart.id}
                    draggable={duzenleyebilir}
                    onDragStart={() => setSurukle(kart.id)}
                    onDragEnd={() => {
                      setSurukle(null);
                      setHedef(null);
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setHedef({ kolon: kolon.id, sira: i });
                    }}
                    onDrop={(e) => {
                      e.stopPropagation();
                      birak(kolon.id, i);
                    }}
                    onClick={() => setAcikKart(kart)}
                    style={{
                      background: "#fff",
                      border: "1px solid #e6e3dc",
                      borderRadius: 6,
                      padding: "8px 10px",
                      cursor: duzenleyebilir ? "grab" : "pointer",
                      opacity: surukle === kart.id ? 0.4 : 1,
                      borderTop:
                        hedef?.kolon === kolon.id && hedef.sira === i && surukle !== null
                          ? "3px solid #11417F"
                          : "1px solid #e6e3dc",
                    }}
                  >
                    <div
                      style={{
                        fontSize: 13,
                        lineHeight: 1.35,
                        textDecoration: kart.tamamlandi_at ? "line-through" : undefined,
                        color: kart.tamamlandi_at ? "#8c8c8c" : undefined,
                      }}
                    >
                      {kart.title}
                    </div>
                    {kart.etiketler.length > 0 && (
                      <Space size={4} wrap style={{ marginBottom: 4 }}>
                        {kart.etiketler.map((e) => (
                          <Tag key={e.id} color={e.renk} style={{ marginInlineEnd: 0 }}>
                            {e.ad || "\u00a0"}
                          </Tag>
                        ))}
                      </Space>
                    )}
                    <Space size={4} wrap style={{ marginTop: 6 }}>
                      {ONCELIK_RENK[kart.oncelik] && (
                        <Tag color={ONCELIK_RENK[kart.oncelik]}>
                          {ONCELIK_ETIKET[kart.oncelik]}
                        </Tag>
                      )}
                      {kart.baglanti &&
                        (baglantiErisimYok(kart.baglanti) ? (
                          <Tooltip title={`${kart.baglanti.ad}: bu kaydı görme yetkiniz yok`}>
                            <Tag>Erişim yok</Tag>
                          </Tooltip>
                        ) : (
                          <Tooltip title={`${kart.baglanti.ad}: ${kart.baglanti.etiket}`}>
                            <Tag color={kart.baglanti.var ? "blue" : "red"}>
                              {kart.baglanti.etiket.slice(0, 18)}
                            </Tag>
                          </Tooltip>
                        ))}
                      {kart.due_date && (
                        <Tag
                          color={
                            !kart.tamamlandi_at && dayjs(kart.due_date).isBefore(dayjs(), "day")
                              ? "red"
                              : undefined
                          }
                        >
                          {dayjs(kart.due_date).format("D MMM")}
                        </Tag>
                      )}
                      {kart.uyeler.map((u) => (
                        <Tag key={u.id}>{u.ad}</Tag>
                      ))}
                      {kart.yorum_sayisi > 0 && <Tag>{kart.yorum_sayisi} yorum</Tag>}
                    </Space>
                  </div>
                ))}

                {duzenleyebilir && (
                  <Input
                    size="small"
                    placeholder="+ hızlı kart (Enter)"
                    prefix={<PlusOutlined style={{ color: "#bfbfbf" }} />}
                    value={hizli[kolon.id] ?? ""}
                    onChange={(e) => setHizli((o) => ({ ...o, [kolon.id]: e.target.value }))}
                    onPressEnter={() => {
                      const baslik = (hizli[kolon.id] ?? "").trim();
                      if (!baslik) return;
                      kartAc.mutate({ column_id: kolon.id, title: baslik });
                      setHizli((o) => ({ ...o, [kolon.id]: "" }));
                    }}
                  />
                )}
              </Space>
            </div>
          );
        })}
      </div>

      <KartPenceresi
        acik={acikKart !== null || yeniKartKolonu !== undefined}
        kart={acikKart}
        pano={pano}
        kolonId={yeniKartKolonu}
        duzenleyebilir={duzenleyebilir}
        onKapat={() => {
          setAcikKart(null);
          setYeniKartKolonu(undefined);
        }}
      />

      <EtiketYonetimi acik={etiketler} pano={pano} onKapat={() => setEtiketler(false)} />

      <PanoModal
        acik={yeniPano}
        form={panoForm}
        yukleniyor={panoAc.isPending}
        onKapat={() => setYeniPano(false)}
        onKaydet={(v) => panoAc.mutate(v)}
      />

      <Modal
        title="Kolon ekle"
        open={yeniKolon}
        onCancel={() => setYeniKolon(false)}
        onOk={() => kolonForm.submit()}
        confirmLoading={kolonEkle.isPending}
        okText="Ekle"
        cancelText="Vazgeç"
      >
        <Form form={kolonForm} layout="vertical" onFinish={(v) => kolonEkle.mutate(v)}>
          <Form.Item name="title" label="Kolon adı" rules={[{ required: true }]}>
            <Input placeholder="Beklemede" />
          </Form.Item>
          <Form.Item
            name="wip_limit"
            label="Kart sınırı"
            extra="Aşıldığında engellenmez, uyarı çıkar. Boş bırakılırsa sınırsız."
          >
            <Select
              allowClear
              placeholder="Sınırsız"
              options={[3, 5, 8, 10, 15, 20].map((n) => ({ value: n, label: `${n} kart` }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

function PanoModal({
  acik,
  form,
  yukleniyor,
  onKapat,
  onKaydet,
}: {
  acik: boolean;
  form: ReturnType<typeof Form.useForm>[0];
  yukleniyor: boolean;
  onKapat: () => void;
  onKaydet: (v: { title: string; description?: string }) => void;
}) {
  return (
    <Modal
      title="Yeni pano"
      open={acik}
      onCancel={onKapat}
      onOk={() => form.submit()}
      confirmLoading={yukleniyor}
      okText="Aç"
      cancelText="Vazgeç"
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => onKaydet(v as { title: string; description?: string })}
      >
        <Form.Item
          name="title"
          label="Pano adı"
          rules={[{ required: true, min: 2, message: "En az 2 karakter" }]}
        >
          <Input placeholder="Montaj Planı" />
        </Form.Item>
        <Form.Item
          name="description"
          label="Açıklama"
          extra="Pano açılırken Yapılacak / Devam ediyor / Bitti kolonları hazır gelir."
        >
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
