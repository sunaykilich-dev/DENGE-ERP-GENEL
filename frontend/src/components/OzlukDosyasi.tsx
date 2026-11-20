/**
 * Personel özlük dosyası (2026-11-20, kullanıcı isteği).
 *
 * Türlere göre klasörler (Kimlik, Adli sicil, SRC…); klasöre tıklayınca
 * belgeler listelenir. Üç kullanım:
 * - `OzlukDosyasi kisiId` — personel kartında, İK (`ik_belge.yonet`): yükle,
 *   sil, tür listesini düzenle.
 * - `OzlukDosyasi benim` — Belgelerim'de, personelin kendi belgeleri (salt okunur).
 * - `IsEkibiBelgeleri soId` — servis işinde, şef/koordinatör: işe atanmış
 *   personelin "işte paylaşılabilir" türdeki belgeleri.
 * Dosyalar yeni sekmede açılır; her açılış sunucuda denetime yazılır.
 */
import {
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
  Skeleton,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

import { ozlukApi, type OzlukBelgesi, type OzlukDosyasi as Dosya, type OzlukTuru } from "../api/ozluk";

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
              </a>
              {b.aciklama && <div className="ozluk-aciklama">{b.aciklama}</div>}
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
  const sayilar = new Map<number, number>();
  for (const b of belgeler) sayilar.set(b.tur_id, (sayilar.get(b.tur_id) ?? 0) + 1);
  return (
    <div className="ozluk-klasorler">
      {turler.map((t) => {
        const adet = sayilar.get(t.id) ?? 0;
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
            <span className="ozluk-klasor-sayi">{adet || "—"}</span>
          </button>
        );
      })}
    </div>
  );
}

function YuklemePenceresi({ kisiId, tur, kapat }: { kisiId: number; tur: OzlukTuru; kapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [dosya, setDosya] = useState<File | null>(null);
  const [bitis, setBitis] = useState<Dayjs | null>(null);
  const [aciklama, setAciklama] = useState("");
  const yukle = useMutation({
    mutationFn: () =>
      ozlukApi.yukle(kisiId, tur.id, dosya!, bitis?.format("YYYY-MM-DD"), aciklama.trim() || undefined),
    onSuccess: () => {
      message.success(`${tur.ad} yüklendi`);
      void qc.invalidateQueries({ queryKey: ["ozluk"] });
      kapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <Modal
      open
      title={`Belge yükle — ${tur.ad}`}
      onCancel={kapat}
      onOk={() => yukle.mutate()}
      okText="Yükle"
      cancelText="Vazgeç"
      okButtonProps={{ disabled: !dosya }}
      confirmLoading={yukle.isPending}
      destroyOnHidden
    >
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
  const [yukleme, setYukleme] = useState<OzlukTuru | null>(null);
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
  return (
    <div className="ozluk">
      <div className="ozluk-bas">
        <span>
          {belgeler.length} belge · {turler.length} klasör
        </span>
        {ik && (
          <Button size="small" type="text" icon={<SettingOutlined />} onClick={() => setTurAcik(true)}>
            Türleri düzenle
          </Button>
        )}
      </div>
      <Klasorler turler={gorunurTurler} belgeler={belgeler} secili={secili} sec={setSecili} />
      {tur && (
        <div className="ozluk-icerik">
          <div className="ozluk-icerik-bas">
            <b>{tur.ad}</b>
            {tur.is_paylasimi && <Tag color="blue">işte paylaşılır</Tag>}
            {ik && tur.aktif && (
              <Button size="small" type="primary" icon={<UploadOutlined />} onClick={() => setYukleme(tur)}>
                Belge yükle
              </Button>
            )}
          </div>
          <BelgeTablosu belgeler={belgeler.filter((b) => b.tur_id === tur.id)} silinebilir={ik} />
        </div>
      )}
      {yukleme && kisiId != null && <YuklemePenceresi kisiId={kisiId} tur={yukleme} kapat={() => setYukleme(null)} />}
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
