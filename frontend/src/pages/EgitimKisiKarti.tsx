/**
 * Eğitim kişi kartı — yönetici görünümü (`/egitim/:id`) ve Gelişim Kartım (TS-150/154/157).
 *
 * Sunucu detay alanlarını (gözlem notu, madde puanı, aksiyon planı, belge no)
 * yalnız `egitim.detay` sahibine ya da kişinin KENDİSİNE gönderir; alan
 * yoksa ilgili bölüm çizilmez (boş göstermek "not yok" sanılırdı). Kartın
 * açılışı sunucuda KVKK erişim loguna yazılır. 375 px'te liste düzeni.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Input,
  List,
  Modal,
  Progress,
  Space,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import type { ApiError } from "../api/client";
import {
  asamaEtiketi,
  egitimApi,
  PLAN_DURUM_ETIKETLERI,
  PLAN_DURUM_RENKLERI,
  type Gozlem,
  type KisiKarti,
} from "../api/egitim";
import { BIRIM_ETIKETLERI } from "../api/personel";
import EkYukleyici from "../components/EkYukleyici";
import { SonucRozeti } from "../components/GozlemFormu";

const tarih = (t: string | null | undefined) => (t ? dayjs(t).format("DD.MM.YYYY") : "—");

function GozlemAyrintisi({ g, kendi }: { g: Gozlem; kendi: boolean }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [yorum, setYorum] = useState("");
  const [acik, setAcik] = useState(false);
  const gordum = useMutation({
    mutationFn: () => egitimApi.gordum(g.id, yorum),
    onSuccess: () => {
      message.success("Onayınız kaydedildi");
      setAcik(false);
      void qc.invalidateQueries({ queryKey: ["egitim-kendim"] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {g.cancelled_at && <Typography.Text type="danger">İptal — {g.cancel_reason}</Typography.Text>}
      {g.maddeler && (
        <List
          size="small"
          dataSource={g.maddeler}
          renderItem={(m) => (
            <List.Item>
              <Space wrap size={4}>
                {m.kritik && <Tag color="red">Kritik</Tag>}
                <Typography.Text>{m.metin}</Typography.Text>
                <Tag>{m.puan === -1 ? `Gözlenmedi (${m.gozlenmedi_gerekcesi ?? ""})` : `${m.puan}/2`}</Tag>
              </Space>
            </List.Item>
          )}
        />
      )}
      {g.notlar !== undefined && <Typography.Text>Not: {g.notlar || "—"}</Typography.Text>}
      {g.aksiyon_plani !== undefined && <Typography.Text>Aksiyon planı: {g.aksiyon_plani || "—"}</Typography.Text>}
      {g.personel_yorumu && <Typography.Text type="secondary">Personel yorumu: {g.personel_yorumu}</Typography.Text>}
      {g.maddeler && (
        <EkYukleyici
          entity="training_observations"
          entityId={g.id}
          kind="GOZLEM_FOTOGRAFI"
          baslik="Gözlem fotoğrafları"
          yazabilir={false}
        />
      )}
      {g.gordu_at ? (
        <Typography.Text type="secondary">Gördü: {dayjs(g.gordu_at).format("DD.MM.YYYY HH:mm")}</Typography.Text>
      ) : (
        kendi &&
        !g.cancelled_at && (
          <Button size="small" type="primary" onClick={() => setAcik(true)}>
            Gördüm
          </Button>
        )
      )}
      <Modal
        open={acik}
        title="Gözlemi gördüğünüzü onaylayın"
        okText="Onayla"
        onOk={() => gordum.mutate()}
        confirmLoading={gordum.isPending}
        onCancel={() => setAcik(false)}
      >
        <Typography.Paragraph type="secondary">Onay geri alınamaz. İsterseniz yorum ekleyin.</Typography.Paragraph>
        <Input.TextArea rows={3} maxLength={900} value={yorum} onChange={(e) => setYorum(e.target.value)} />
      </Modal>
    </Space>
  );
}

export function KisiKartiGorunumu({ kart }: { kart: KisiKarti }) {
  const k = kart.kisi;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Card size="small">
        <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
          <Descriptions.Item label="Personel">{k.ad}</Descriptions.Item>
          <Descriptions.Item label="Ünvan">{k.unvan ?? "—"}</Descriptions.Item>
          <Descriptions.Item label="Birim">
            {k.birimler.map((b) => BIRIM_ETIKETLERI[b] ?? b).join(", ") || "Birimsiz"}
          </Descriptions.Item>
          <Descriptions.Item label="Durum">
            {k.calisiyor ? <Tag color="green">Çalışıyor</Tag> : <Tag>Ayrıldı / pasif</Tag>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {kart.bos && <Empty description="Henüz eğitim kaydınız yok" />}

      <Card size="small" title="Eğitim planları">
        <List
          size="small"
          dataSource={kart.planlar}
          locale={{ emptyText: "Plan yok" }}
          renderItem={(p) => (
            <List.Item>
              <Space wrap size={4}>
                <Typography.Text strong>{p.plan_yili}</Typography.Text>
                <Typography.Text>{p.kurs}</Typography.Text>
                <Tag color={PLAN_DURUM_RENKLERI[p.status]}>{PLAN_DURUM_ETIKETLERI[p.status] ?? p.status}</Tag>
                <Typography.Text type={p.geciken ? "danger" : "secondary"}>Hedef {tarih(p.hedef_tarih)}</Typography.Text>
                {p.completed_on && (
                  <Typography.Text type="secondary">
                    Tamamlandı {tarih(p.completed_on)}
                    {p.gec ? " (geç)" : ""}
                  </Typography.Text>
                )}
                {p.status === "IPTAL" && <Typography.Text type="secondary">— {p.durum_gerekcesi}</Typography.Text>}
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Card size="small" title="Saha gözlemleri">
        {kart.gozlemler.length ? (
          <Collapse
            size="small"
            items={kart.gozlemler.map((g) => ({
              key: g.id,
              label: (
                <Space wrap size={4}>
                  <Typography.Text>{tarih(g.gozlem_tarihi)}</Typography.Text>
                  <Typography.Text>{g.kurs}</Typography.Text>
                  <Typography.Text type="secondary">{asamaEtiketi(g.asama)}</Typography.Text>
                  <SonucRozeti g={g} />
                </Space>
              ),
              children: <GozlemAyrintisi g={g} kendi={kart.kendi} />,
            }))}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Gözlem yok" />
        )}
      </Card>

      {kart.faaliyetler.length > 0 && (
        <Card size="small" title="Düzeltici faaliyetler">
          <List
            size="small"
            dataSource={kart.faaliyetler}
            renderItem={(f) => (
              <List.Item>
                <Space wrap size={4}>
                  <Typography.Text>{f.kurs}</Typography.Text>
                  <Tag color={f.status === "ACIK" ? (f.gecikmis ? "red" : "orange") : "green"}>
                    {f.status === "ACIK" ? "Açık" : "Kapatıldı"}
                  </Tag>
                  <Typography.Text type="secondary">Termin {tarih(f.termin)}</Typography.Text>
                  {f.gozlem_iptal && <Tag>Gözlemi iptal edildi</Tag>}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}

      <Card size="small" title="Yetkinlikler">
        <List
          size="small"
          dataSource={kart.yetkinlikler}
          locale={{ emptyText: "Değerlendirme yok" }}
          renderItem={(y) => (
            <List.Item>
              <Space wrap size={6} style={{ width: "100%" }}>
                <Typography.Text>
                  {y.yetkinlik} {y.kritik && <Tag color="red">Kritik</Tag>}
                </Typography.Text>
                <Progress
                  percent={(y.mevcut_seviye / 4) * 100}
                  steps={4}
                  size="small"
                  format={() => `${y.mevcut_seviye}/4 (hedef ${y.hedef_seviye})`}
                  status={y.mevcut_seviye < y.hedef_seviye ? "exception" : "success"}
                />
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Card size="small" title="Geçerlilik ve belgeler">
        <List
          size="small"
          dataSource={kart.gecerlilik}
          locale={{ emptyText: "Takip edilen geçerlilik yok" }}
          renderItem={(g) => (
            <List.Item>
              <Space wrap size={4}>
                <Typography.Text>{g.ad}</Typography.Text>
                <Tag color={g.durum === "DOLDU" ? "red" : g.durum === "DOLACAK" ? "orange" : "green"}>
                  {g.durum === "DOLDU" ? "Süresi doldu" : g.durum === "DOLACAK" ? "Süresi doluyor" : "Geçerli"}
                </Tag>
                <Typography.Text type="secondary">Bitiş {tarih(g.bitis)}</Typography.Text>
              </Space>
            </List.Item>
          )}
        />
        {kart.belgeler.some((b) => b.cancelled_at) && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            İptal edilen belgeler: {kart.belgeler.filter((b) => b.cancelled_at).map((b) => `${b.belge_adi} (${b.cancel_reason})`).join(", ")}
          </Typography.Text>
        )}
      </Card>

      {kart.katilimlar.length > 0 && (
        <Card size="small" title="Katılım ve sınav">
          <List
            size="small"
            dataSource={kart.katilimlar}
            renderItem={(a) => (
              <List.Item>
                <Space wrap size={4}>
                  <Typography.Text>{tarih(a.oturum_tarihi)}</Typography.Text>
                  <Typography.Text>{a.kurs}</Typography.Text>
                  {a.katildi ? <Tag color="green">Katıldı</Tag> : <Tag>Katılmadı</Tag>}
                  {a.son_puan != null && <Typography.Text type="secondary">Son sınav {a.son_puan}</Typography.Text>}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}
    </Space>
  );
}
