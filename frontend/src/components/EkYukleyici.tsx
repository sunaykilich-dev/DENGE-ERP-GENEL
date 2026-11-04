import { DeleteOutlined, FileOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Empty, Image, Popconfirm, Space, Tag, Typography, Upload } from "antd";

import { api } from "../api/client";

export interface Ek {
  id: number;
  entity: string;
  entity_id: number;
  kind: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  gorsel: boolean;
  notes: string | null;
  uploaded_at: string;
}

interface Props {
  entity: string;
  entityId: number;
  /** Yüklenecek ekin türü — `EK_TURLERI` içinden. */
  kind: string;
  baslik: string;
  aciklama?: string;
  yazabilir: boolean;
  /** Yalnız bu türdeki ekler listelensin. */
  yalnizTur?: boolean;
  accept?: string;
  /**
   * Mobilde doğrudan kamerayı açar (`<input capture>`; TS-077). Yalnız
   * ekleme: verilmezse davranış eskisi gibidir.
   */
  capture?: boolean | "user" | "environment";
  /**
   * Saha (mobil) kullanımı: düğmeler en az 44 px dokunma hedefi olur
   * (rol testi B10). Masaüstü ekranlarda verilmez, görünüm değişmez.
   */
  buyukDugme?: boolean;
}

const boyut = (b: number) =>
  b < 1024 * 1024 ? `${Math.round(b / 1024)} KB` : `${(b / (1024 * 1024)).toFixed(1)} MB`;

/**
 * Dosya eki listesi + yükleme.
 *
 * Tek bileşen, bütün modüller için: ürün görseli, broşür, montaj fotoğrafı ve
 * ruhsat aynı uçtan (`/api/ekler`) beslenir. AntD `Upload`'un kendi isteği
 * yerine `customRequest` kullanılıyor çünkü CSRF başlığı (`X-Requested-With`)
 * ve `credentials` ayarı bizim istemcimizde tanımlı.
 */
export default function EkYukleyici({
  entity,
  entityId,
  kind,
  baslik,
  aciklama,
  yazabilir,
  yalnizTur = true,
  accept,
  capture,
  buyukDugme = false,
}: Props) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const anahtar = ["ekler", entity, entityId];

  const ekler = useQuery({
    queryKey: anahtar,
    queryFn: () => api.get<Ek[]>(`/api/ekler/${entity}/${entityId}`),
    enabled: !!entityId,
  });

  const sil = useMutation({
    mutationFn: (id: number) => api.delete(`/api/ekler/${id}`),
    onSuccess: () => {
      message.success("Ek silindi");
      void qc.invalidateQueries({ queryKey: anahtar });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const liste = (ekler.data ?? []).filter((e) => !yalnizTur || e.kind === kind);
  const dugmeBoyu = buyukDugme ? undefined : ("small" as const);
  const dokunma = buyukDugme ? { minHeight: 44, minWidth: 44 } : undefined;

  async function yukle(dosya: File) {
    const govde = new FormData();
    govde.append("file", dosya);
    const res = await fetch(
      `/api/ekler/${entity}/${entityId}?kind=${encodeURIComponent(kind)}`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        body: govde,
      },
    );
    if (!res.ok) {
      let mesaj = `Yüklenemedi (${res.status})`;
      try {
        const g = await res.json();
        if (typeof g?.detail === "string") mesaj = g.detail;
      } catch {
        /* gövde JSON değil */
      }
      throw new Error(mesaj);
    }
    void qc.invalidateQueries({ queryKey: anahtar });
  }

  return (
    <Card
      size="small"
      title={baslik}
      extra={
        yazabilir && (
          <Upload
            accept={accept}
            capture={capture}
            showUploadList={false}
            customRequest={({ file, onSuccess, onError }) => {
              yukle(file as File)
                .then(() => {
                  message.success("Yüklendi");
                  onSuccess?.({});
                })
                .catch((e: Error) => {
                  message.error(e.message);
                  onError?.(e);
                });
            }}
          >
            <Button size={dugmeBoyu} style={dokunma} icon={<UploadOutlined />}>
              Yükle
            </Button>
          </Upload>
        )
      }
    >
      {aciklama && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
          {aciklama}
        </Typography.Paragraph>
      )}

      {liste.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Dosya yok" />
      ) : (
        <Space wrap size={[12, 12]}>
          {liste.map((e) => (
            <div key={e.id} style={{ width: 128, textAlign: "center" }}>
              {e.gorsel ? (
                <Image
                  src={`/api/ekler/dosya/${e.id}`}
                  alt={e.file_name}
                  width={128}
                  height={96}
                  style={{ objectFit: "cover", borderRadius: 4 }}
                />
              ) : (
                <a
                  href={`/api/ekler/dosya/${e.id}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "flex",
                    width: 128,
                    height: 96,
                    alignItems: "center",
                    justifyContent: "center",
                    border: "1px solid #e0dace",
                    borderRadius: 4,
                    background: "#fbf9f5",
                  }}
                >
                  <Space orientation="vertical" size={2}>
                    <FileOutlined style={{ fontSize: 22 }} />
                    <Tag>{e.mime_type.split("/").pop()?.slice(0, 8)}</Tag>
                  </Space>
                </a>
              )}
              <Typography.Text
                ellipsis={{ tooltip: e.file_name }}
                style={{ display: "block", fontSize: 12, marginTop: 4 }}
              >
                {e.file_name}
              </Typography.Text>
              <Space size={4}>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {boyut(e.size_bytes)}
                </Typography.Text>
                {yazabilir && (
                  <Popconfirm
                    title="Ek silinsin mi?"
                    okText="Sil"
                    cancelText="Vazgeç"
                    onConfirm={() => sil.mutate(e.id)}
                  >
                    <Button
                      size={dugmeBoyu}
                      style={dokunma}
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      aria-label="Eki sil"
                    />
                  </Popconfirm>
                )}
              </Space>
            </div>
          ))}
        </Space>
      )}
    </Card>
  );
}
