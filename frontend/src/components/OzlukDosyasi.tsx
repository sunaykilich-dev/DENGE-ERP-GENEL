/**
 * Personel özlük dosyası (2026-11-20, kullanıcı isteği).
 *
 * Türlere göre klasörler (Kimlik, Adli sicil, SRC…); klasöre tıklayınca
 * belgeler listelenir. Üç kullanım:
 * - `OzlukDosyasi kisiId` — personel kartında, İK (`ik_belge.yonet`): yükle,
 *   sil, tür listesini düzenle.
 * - `OzlukDosyasi benim` — Belgelerim'de, personelin kendi belgeleri; "Belge
 *   yükle" ile kendi dosyasına yükler (2026-11-23). Bu belge İK onaylayana dek
 *   "Onay bekliyor"dur, reddedilirse gerekçesiyle görünür kalır.
 * - `OzlukBekleyenler` — Personel ekranında İK: onay bekleyen bütün belgeler.
 * - `IsEkibiBelgeleri soId` — servis işinde, şef/koordinatör: işe atanmış
 *   personelin "işte paylaşılabilir" türdeki belgeleri.
 * Dosyalar yeni sekmede açılır; her açılış sunucuda denetime yazılır.
 */
import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  FileOutlined,
  FolderFilled,
  FolderOpenFilled,
  PlusOutlined,
  SettingOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

import {
  ozlukApi,
  type BekleyenOzlukBelgesi,
  type OzlukBelgesi,
  type OzlukDosyasi as Dosya,
  type OzlukTuru,
} from "../api/ozluk";

function boyut(b: number): string {
  return b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`;
}

function GecerlilikEtiketi({ tarih }: { tarih: string | null }) {
  if (!tarih) return null;
  const kalan = dayjs(tarih).diff(dayjs().startOf("day"), "day");
  const renk = kalan < 0 ? "red" : kalan <= 30 ? "orange" : "default";
  return (
    <Tag color={renk} style={{ marginInlineEnd: 0 }}>
      {kalan < 0 ? "süresi doldu" : "geçerli"} · {dayjs(tarih).format("DD.MM.YYYY")}
    </Tag>
  );
}

/** Kendi yüklemesinin durumu; onaylı belgede etiket yok. */
function DurumEtiketi({ belge }: { belge: OzlukBelgesi }) {
  if (belge.durum === "ONAY_BEKLIYOR") return <Tag color="gold">Onay bekliyor</Tag>;
  if (belge.durum === "REDDEDILDI") return <Tag color="red">Reddedildi</Tag>;
  return null;
}

function ozlukTazele(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["ozluk"] });
  void qc.invalidateQueries({ queryKey: ["uyarilar"] });
}

/** İK: bekleyen belgeye "Onayla" / "Reddet" (gerekçe sorar). */
function KararDugmeleri({ belge }: { belge: OzlukBelgesi }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [redAcik, setRedAcik] = useState(false);
  const [gerekce, setGerekce] = useState("");
  const onayla = useMutation({
    mutationFn: () => ozlukApi.onayla(belge),
    onSuccess: () => {
      void message.success("Belge onaylandı");
      ozlukTazele(qc);
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const reddet = useMutation({
    mutationFn: () => ozlukApi.reddet(belge, gerekce.trim()),
    onSuccess: () => {
      void message.success("Belge reddedildi; personel gerekçeyi görür");
      setRedAcik(false);
      ozlukTazele(qc);
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <Space size={4}>
      <Button
        size="small"
        type="primary"
        icon={<CheckOutlined />}
        loading={onayla.isPending}
        onClick={() => onayla.mutate()}
      >
        Onayla
      </Button>
      <Button size="small" danger icon={<CloseOutlined />} onClick={() => setRedAcik(true)}>
        Reddet
      </Button>
      {redAcik && (
        <Modal
          open
          title={`Reddet — ${belge.dosya_adi}`}
          okText="Reddet"
          cancelText="Vazgeç"
          okButtonProps={{ danger: true, disabled: gerekce.trim().length < 3 }}
          confirmLoading={reddet.isPending}
          onOk={() => reddet.mutate()}
          onCancel={() => setRedAcik(false)}
          destroyOnHidden
        >
          <Input.TextArea
            autoFocus
            rows={3}
            maxLength={500}
            value={gerekce}
            onChange={(e) => setGerekce(e.target.value)}
            placeholder="Red gerekçesi (personel görür; ör. fotoğraf okunmuyor)"
          />
        </Modal>
      )}
    </Space>
  );
}

function BelgeTablosu({
  belgeler,
  isId,
  silinebilir,
}: {
  belgeler: OzlukBelgesi[];
  isId?: number;
  silinebilir?: boolean;
}) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const sil = useMutation({
    mutationFn: ozlukApi.sil,
    onSuccess: () => {
      message.success("Belge kaldırıldı");
      void qc.invalidateQueries({ queryKey: ["ozluk"] });
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <Table<OzlukBelgesi>
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={belgeler}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Bu klasörde belge yok" /> }}
      columns={[
        {
          title: "Dosya",
          key: "dosya",
          render: (_, b) => (
            <div>
              <a href={ozlukApi.dosyaUrl(b.id, isId)} target="_blank" rel="noreferrer">
                <FileOutlined /> {b.dosya_adi}
              </a>{" "}
              <DurumEtiketi belge={b} />
              {b.aciklama && <div className="ozluk-aciklama">{b.aciklama}</div>}
              {b.durum === "REDDEDILDI" && b.red_gerekcesi && (
                <div className="ozluk-red">Reddedildi: {b.red_gerekcesi}</div>
              )}
              {silinebilir && b.durum === "ONAY_BEKLIYOR" && (
                <div style={{ marginTop: 4 }}>
                  <KararDugmeleri belge={b} />
                </div>
              )}
            </div>
          ),
        },
        {
          title: "Geçerlilik",
          key: "gecerlilik",
          width: 170,
          render: (_, b) => (b.gecerlilik_bitis ? <GecerlilikEtiketi tarih={b.gecerlilik_bitis} /> : "Süresiz"),
        },
        {
          title: "Yüklendi",
          dataIndex: "created_at",
          width: 110,
          responsive: ["sm"],
          render: (v: string, b) => (
            <Tooltip title={boyut(b.size_bytes)}>{dayjs(v).format("DD.MM.YYYY")}</Tooltip>
          ),
        },
        ...(silinebilir
          ? [
              {
                title: "",
                key: "sil",
                width: 48,
                render: (_: unknown, b: OzlukBelgesi) => (
                  <Popconfirm
                    title="Belge kaldırılsın mı?"
                    okText="Kaldır"
                    cancelText="Vazgeç"
                    onConfirm={() => sil.mutateAsync(b.id)}
                  >
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label="Belgeyi kaldır" />
                  </Popconfirm>
                ),
              },
            ]
          : []),
      ]}
    />
  );
}

function Klasorler({
  turler,
  belgeler,
  secili,
  sec,
}: {
  turler: OzlukTuru[];
  belgeler: OzlukBelgesi[];
  secili: number | null;
  sec: (id: number | null) => void;
}) {
  // Klasör sayısı yalnız onaylı (geçerli) belgedir; bekleyen ayrıca yazılır.
  const sayilar = new Map<number, number>();
  const bekleyen = new Map<number, number>();
  for (const b of belgeler) {
    if (b.durum === "ONAYLANDI") sayilar.set(b.tur_id, (sayilar.get(b.tur_id) ?? 0) + 1);
    else if (b.durum === "ONAY_BEKLIYOR") bekleyen.set(b.tur_id, (bekleyen.get(b.tur_id) ?? 0) + 1);
  }
  return (
    <div className="ozluk-klasorler">
      {turler.map((t) => {
        const adet = sayilar.get(t.id) ?? 0;
        const bekleyenAdet = bekleyen.get(t.id) ?? 0;
        const acik = secili === t.id;
        return (
          <button
            key={t.id}
            type="button"
            className={`ozluk-klasor${acik ? " acik" : ""}${adet ? "" : " bos"}`}
            onClick={() => sec(acik ? null : t.id)}
            aria-expanded={acik}
          >
            {acik ? <FolderOpenFilled className="ozluk-ikon" /> : <FolderFilled className="ozluk-ikon" />}
            <span className="ozluk-klasor-ad">{t.ad}</span>
            {bekleyenAdet > 0 && <span className="ozluk-klasor-bekleyen">{bekleyenAdet} bekliyor</span>}
            <span className="ozluk-klasor-sayi">{adet || "—"}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Yükleme penceresi. İK (`kisiId`): seçili klasöre, doğrudan onaylı. Kişinin
 * kendisi (`turler` verilir): türü seçer; belge İK onayına düşer.
 */
function YuklemePenceresi({
  kisiId,
  tur,
  turler,
  kapat,
}: {
  kisiId?: number;
  tur: OzlukTuru | null;
  turler?: OzlukTuru[];
  kapat: () => void;
}) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const kendi = kisiId == null;
  const [turId, setTurId] = useState<number | null>(tur?.id ?? null);
  const [dosya, setDosya] = useState<File | null>(null);
  const [bitis, setBitis] = useState<Dayjs | null>(null);
  const [aciklama, setAciklama] = useState("");
  const turAdi = (tur?.id === turId ? tur?.ad : turler?.find((t) => t.id === turId)?.ad) ?? "Belge";
  const yukle = useMutation({
    mutationFn: () => {
      const bitisMetni = bitis?.format("YYYY-MM-DD");
      const not = aciklama.trim() || undefined;
      return kendi
        ? ozlukApi.kendiYukle(turId!, dosya!, bitisMetni, not)
        : ozlukApi.yukle(kisiId, turId!, dosya!, bitisMetni, not);
    },
    onSuccess: () => {
      void message.success(kendi ? `${turAdi} İK onayına gönderildi` : `${turAdi} yüklendi`);
      ozlukTazele(qc);
      kapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <Modal
      open
      title={kendi ? "Belge yükle" : `Belge yükle — ${turAdi}`}
      onCancel={kapat}
      onOk={() => yukle.mutate()}
      okText={kendi ? "Gönder" : "Yükle"}
      cancelText="Vazgeç"
      okButtonProps={{ disabled: !dosya || turId == null }}
      confirmLoading={yukle.isPending}
      destroyOnHidden
    >
      {kendi && (
        <>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            Yüklediğiniz belge İK onaylayana kadar &quot;Onay bekliyor&quot; görünür ve geçerli belge sayılmaz.
          </Typography.Paragraph>
          <Select
            style={{ width: "100%", marginBottom: 12 }}
            placeholder="Belge türü seçin"
            value={turId ?? undefined}
            onChange={setTurId}
            showSearch={{ optionFilterProp: "label" }}
            options={(turler ?? []).filter((t) => t.aktif).map((t) => ({ value: t.id, label: t.ad }))}
          />
        </>
      )}
      <Upload.Dragger
        maxCount={1}
        accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.docx"
        beforeUpload={(f) => {
          setDosya(f);
          return false;
        }}
        onRemove={() => setDosya(null)}
        fileList={dosya ? [{ uid: "1", name: dosya.name, status: "done" }] : []}
      >
        <p>
          <UploadOutlined /> Dosyayı sürükleyin ya da seçin
        </p>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          PDF, fotoğraf ya da Word · en çok 25 MB
        </Typography.Text>
      </Upload.Dragger>
      <div className="ozluk-form-satir">
        <span>Geçerlilik bitişi (süreli belgede)</span>
        <DatePicker value={bitis} onChange={setBitis} format="DD.MM.YYYY" placeholder="Süresiz" />
      </div>
      <Input.TextArea
        value={aciklama}
        onChange={(e) => setAciklama(e.target.value)}
        maxLength={500}
        rows={2}
        placeholder="Açıklama (isteğe bağlı)"
      />
    </Modal>
  );
}

function TurDuzenleme({ kapat }: { kapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [yeniAd, setYeniAd] = useState("");
  const turler = useQuery({ queryKey: ["ozluk", "turler", "tumu"], queryFn: () => ozlukApi.turler(true) });
  const tazele = () => void qc.invalidateQueries({ queryKey: ["ozluk"] });
  const degistir = useMutation({
    mutationFn: ({ t, d }: { t: OzlukTuru; d: Parameters<typeof ozlukApi.turDegistir>[1] }) =>
      ozlukApi.turDegistir(t, d),
    onSuccess: tazele,
    onError: (e: Error) => void message.error(e.message),
  });
  const ekle = useMutation({
    mutationFn: () => ozlukApi.turEkle(yeniAd.trim(), false),
    onSuccess: () => {
      setYeniAd("");
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <Modal open title="Belge türleri" onCancel={kapat} footer={null} width={640} destroyOnHidden>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        "İşte paylaşılır" işaretli türleri saha şefi ve koordinatör, işe atanmış personel için iş ayrıntısından
        görebilir (ör. müşteri sahaya girişte SRC, İSG ister). Kaldırılan tür yeni yüklemede çıkmaz; eski
        belgeler silinmez.
      </Typography.Paragraph>
      {turler.isLoading ? (
        <Skeleton active />
      ) : (
        <Table<OzlukTuru>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={turler.data ?? []}
          rowClassName={(t) => (t.aktif ? "" : "ozluk-tur-pasif")}
          columns={[
            {
              title: "Ad",
              key: "ad",
              render: (_, t) => (
                <Typography.Text
                  editable={
                    t.aktif
                      ? {
                          onChange: (ad) => {
                            if (ad.trim() && ad.trim() !== t.ad) degistir.mutate({ t, d: { ad: ad.trim() } });
                          },
                        }
                      : false
                  }
                >
                  {t.ad}
                </Typography.Text>
              ),
            },
            {
              title: "İşte paylaşılır",
              key: "pay",
              width: 120,
              align: "center",
              render: (_, t) => (
                <Switch
                  size="small"
                  checked={t.is_paylasimi}
                  disabled={!t.aktif}
                  onChange={(v) => degistir.mutate({ t, d: { is_paylasimi: v } })}
                />
              ),
            },
            {
              title: "",
              key: "aktif",
              width: 110,
              align: "right",
              render: (_, t) => (
                <Button size="small" type="link" onClick={() => degistir.mutate({ t, d: { aktif: !t.aktif } })}>
                  {t.aktif ? "Kaldır" : "Geri al"}
                </Button>
              ),
            },
          ]}
        />
      )}
      <div className="ozluk-form-satir">
        <Input
          value={yeniAd}
          onChange={(e) => setYeniAd(e.target.value)}
          maxLength={80}
          placeholder="Yeni tür adı (ör. Sağlık Raporu)"
          onPressEnter={() => yeniAd.trim().length >= 2 && ekle.mutate()}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={yeniAd.trim().length < 2}
          loading={ekle.isPending}
          onClick={() => ekle.mutate()}
        >
          Ekle
        </Button>
      </div>
    </Modal>
  );
}

/** Kişinin özlük dosyası: İK modu (`kisiId`) ya da kişinin kendisi (`benim`). */
export default function OzlukDosyasi({ kisiId, benim }: { kisiId?: number; benim?: boolean }) {
  const [secili, setSecili] = useState<number | null>(null);
  // İK: seçili klasöre yükler; kişi: "yeni" (tür seçer) ya da açık klasör.
  const [yukleme, setYukleme] = useState<OzlukTuru | "yeni" | null>(null);
  const [turAcik, setTurAcik] = useState(false);
  const ik = !benim && kisiId != null;
  const dosya = useQuery<Dosya>({
    queryKey: ["ozluk", benim ? "benim" : kisiId],
    queryFn: () => (benim ? ozlukApi.benim() : ozlukApi.kisi(kisiId!)),
  });
  if (dosya.error) return <Alert type="error" showIcon message={(dosya.error as Error).message} />;
  if (!dosya.data) return <Skeleton active paragraph={{ rows: 3 }} />;
  const { turler, belgeler } = dosya.data;
  // Sunucu kaldırılmış ama belgesi olan türleri de gerçek adıyla gönderir;
  // yalnız tanınmayan tür (savunma) "Diğer" klasörüne düşer.
  const gorunurTurler = [
    ...turler,
    ...[...new Set(belgeler.map((b) => b.tur_id))]
      .filter((id) => !turler.some((t) => t.id === id))
      .map((id) => ({ id, ad: "Diğer", sira: 9999, aktif: false, is_paylasimi: false, version: 0 })),
  ];
  const tur = gorunurTurler.find((t) => t.id === secili) ?? null;
  const onayli = belgeler.filter((b) => b.durum === "ONAYLANDI").length;
  const bekleyen = belgeler.filter((b) => b.durum === "ONAY_BEKLIYOR").length;
  return (
    <div className="ozluk">
      <div className="ozluk-bas">
        <span>
          {onayli} belge · {turler.length} klasör
          {bekleyen > 0 && (
            <>
              {" "}
              · <Tag color="gold">{bekleyen} onay bekliyor</Tag>
            </>
          )}
        </span>
        <span className="ozluk-bas-sag">
          {benim && (
            <Button size="small" type="primary" icon={<UploadOutlined />} onClick={() => setYukleme("yeni")}>
              Belge yükle
            </Button>
          )}
          {ik && (
            <Button size="small" type="text" icon={<SettingOutlined />} onClick={() => setTurAcik(true)}>
              Türleri düzenle
            </Button>
          )}
        </span>
      </div>
      <Klasorler turler={gorunurTurler} belgeler={belgeler} secili={secili} sec={setSecili} />
      {tur && (
        <div className="ozluk-icerik">
          <div className="ozluk-icerik-bas">
            <b>{tur.ad}</b>
            {tur.is_paylasimi && <Tag color="blue">işte paylaşılır</Tag>}
            {(ik || benim) && tur.aktif && (
              <Button size="small" type="primary" icon={<UploadOutlined />} onClick={() => setYukleme(tur)}>
                Belge yükle
              </Button>
            )}
          </div>
          <BelgeTablosu belgeler={belgeler.filter((b) => b.tur_id === tur.id)} silinebilir={ik} />
        </div>
      )}
      {yukleme && ik && (
        <YuklemePenceresi
          kisiId={kisiId}
          tur={yukleme === "yeni" ? null : yukleme}
          kapat={() => setYukleme(null)}
        />
      )}
      {yukleme && benim && (
        <YuklemePenceresi tur={yukleme === "yeni" ? null : yukleme} turler={turler} kapat={() => setYukleme(null)} />
      )}
      {turAcik && <TurDuzenleme kapat={() => setTurAcik(false)} />}
    </div>
  );
}

/** Servis işine atanmış personelin işte paylaşılabilir belgeleri (şef/koordinatör). */
export function IsEkibiBelgeleri({ soId }: { soId: number }) {
  const veri = useQuery({ queryKey: ["ozluk", "is", soId], queryFn: () => ozlukApi.isEkibi(soId) });
  if (veri.error) return <Alert type="error" showIcon message={(veri.error as Error).message} />;
  if (!veri.data) return <Skeleton active paragraph={{ rows: 2 }} />;
  const { kisiler, turler } = veri.data;
  if (!kisiler.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="İşe atanmış personel yok" />;
  const turAdi = new Map(turler.map((t) => [t.id, t.ad]));
  return (
    <div className="ozluk-ekip">
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Paylaşılan türler: {turler.map((t) => t.ad).join(", ") || "yok"}. Açtığınız belge kayıt altına alınır.
      </Typography.Text>
      {kisiler.map((k) => (
        <div key={k.user_id} className="ozluk-ekip-kisi">
          <b>{k.ad}</b>
          {k.belgeler.length === 0 ? (
            <Typography.Text type="secondary"> — paylaşılan belge yok</Typography.Text>
          ) : (
            <ul>
              {k.belgeler.map((b) => (
                <li key={b.id}>
                  <Tag style={{ marginInlineEnd: 6 }}>{turAdi.get(b.tur_id) ?? "Belge"}</Tag>
                  <a href={ozlukApi.dosyaUrl(b.id, soId)} target="_blank" rel="noreferrer">
                    {b.dosya_adi}
                  </a>{" "}
                  <GecerlilikEtiketi tarih={b.gecerlilik_bitis} />
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * İK (Personel ekranı): personelin kendi yüklediği, onay bekleyen bütün
 * belgeler. Yoksa hiçbir şey çizmez; varsa tek satır uyarı + "Göster".
 * `acik` ile (uyarı zilinden `?ozluk=bekleyen`) liste doğrudan açılır.
 */
export function OzlukBekleyenler({ acik: ilkAcik = false }: { acik?: boolean }) {
  const [acik, setAcik] = useState(ilkAcik);
  const veri = useQuery({ queryKey: ["ozluk", "bekleyenler"], queryFn: ozlukApi.bekleyenler });
  const liste = veri.data ?? [];
  if (!liste.length && !acik) return null;
  return (
    <>
      {liste.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title={`${liste.length} özlük belgesi onay bekliyor`}
          description="Personelin kendi yüklediği belge, onaylanana kadar geçerli sayılmaz ve işte paylaşılmaz."
          action={
            <Button size="small" onClick={() => setAcik(true)}>
              Göster
            </Button>
          }
        />
      )}
      {acik && (
        <Modal open title="Onay bekleyen özlük belgeleri" footer={null} width={820} onCancel={() => setAcik(false)}>
          <Table<BekleyenOzlukBelgesi>
            rowKey="id"
            size="small"
            pagination={false}
            loading={veri.isLoading}
            dataSource={liste}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Onay bekleyen belge yok" /> }}
            columns={[
              { title: "Personel", dataIndex: "kisi_adi", width: 170 },
              { title: "Tür", dataIndex: "tur_adi", width: 150 },
              {
                title: "Dosya",
                key: "dosya",
                render: (_, b) => (
                  <div>
                    <a href={ozlukApi.dosyaUrl(b.id)} target="_blank" rel="noreferrer">
                      <FileOutlined /> {b.dosya_adi}
                    </a>
                    {b.aciklama && <div className="ozluk-aciklama">{b.aciklama}</div>}
                    {b.gecerlilik_bitis && <GecerlilikEtiketi tarih={b.gecerlilik_bitis} />}
                  </div>
                ),
              },
              {
                title: "Yüklendi",
                dataIndex: "created_at",
                width: 100,
                responsive: ["sm"],
                render: (v: string) => dayjs(v).format("DD.MM.YYYY"),
              },
              { title: "", key: "karar", width: 190, render: (_, b) => <KararDugmeleri belge={b} /> },
            ]}
          />
        </Modal>
      )}
    </>
  );
}
