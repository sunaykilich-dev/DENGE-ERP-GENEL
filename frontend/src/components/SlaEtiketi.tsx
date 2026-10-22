import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Descriptions, Form, Input, Modal, Select, Spin, Tag, Tooltip } from "antd";
import dayjs from "dayjs";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import { operasyonApi, SLA_RENKLERI, sureMetni, type SlaBlogu } from "../api/servisOperasyon";
import { useAuth } from "../auth/AuthContext";

/**
 * SLA etiketi — sunucunun `sla` bloğunu GÖSTERİR, hesaplamaz (TS-081, E10-18).
 *
 * Durum, kalan dakika, hedef ve PB vadesi sunucudaki tek SLA modülünden gelir;
 * burada yalnız metne çevrilir: "Kalan 3 sa 20 dk" / "Gecikti 1 sa" /
 * "Durduruldu" / "Vade: Ekim 2026". Öncelikten saat türetilmez (grep testi).
 * Servis işi detayı, Operasyon Merkezi ve Benim İşlerim aynı bileşeni kullanır.
 */
export interface SlaEtiketiProps {
  sla: SlaBlogu | null | undefined;
  /** Kısa: yalnız etiket (liste satırı); uzun: hedef zamanı da yazılır. */
  kisa?: boolean;
}

function etiketMetni(sla: SlaBlogu): string {
  if (sla.durum === "SLA_DISI_PB") return sla.vade_ay ? `Vade: ${sla.vade_ay}` : sla.ad;
  if (sla.kalan_dk == null) return sla.ad;
  if (sla.durum === "ASILDI") return `Gecikti ${sureMetni(sla.kalan_dk)}`;
  if (sla.durum === "DURDURULDU") return `Durduruldu (kalan ${sureMetni(sla.kalan_dk)})`;
  return `Kalan ${sureMetni(sla.kalan_dk)}`;
}

export default function SlaEtiketi({ sla, kisa = true }: SlaEtiketiProps) {
  if (!sla) return null;
  const metin = etiketMetni(sla);
  const ipucu = [
    `SLA: ${sla.ad}`,
    sla.hedef_at ? `Hedef: ${dayjs(sla.hedef_at).format("DD.MM.YYYY HH:mm")}` : null,
    sla.ilk_hedef_at && sla.ilk_hedef_at !== sla.hedef_at
      ? `İlk hedef: ${dayjs(sla.ilk_hedef_at).format("DD.MM.YYYY HH:mm")}`
      : null,
    sla.durdurulan_dk ? `İş beklemesiyle durdurulan: ${sureMetni(sla.durdurulan_dk)}` : null,
    sla.kaynak === "GECIS" ? "Hedef SLA yürürlük anından damgalandı" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Tooltip title={ipucu}>
      <span style={{ whiteSpace: "nowrap" }}>
        <Tag color={SLA_RENKLERI[sla.durum] ?? "default"} style={{ marginInlineEnd: 0 }}>
          {metin}
        </Tag>
        {!kisa && sla.hedef_at && (
          <span style={{ marginInlineStart: 6, fontSize: 12, color: "var(--ant-color-text-secondary)" }}>
            Hedef {dayjs(sla.hedef_at).format("DD.MM.YYYY HH:mm")}
          </span>
        )}
      </span>
    </Tooltip>
  );
}

const zaman = (t: string | null | undefined) => (t ? dayjs(t).format("DD.MM.YYYY HH:mm") : "—");

/**
 * SLA kartı + kapanış bilgisi penceresi (TS-081/084; E10-01/04).
 *
 * `GET /operasyon/isler/{id}/sla` kartını gösterir; `servis.kapat` veya
 * `servis.tamamla` izniyle gecikme nedeni (yalnız SLA aşılmış işte) ve tekrar
 * arıza teyidi (yalnız aday işte) `PUT .../kapanis-bilgisi` ile kaydedilir.
 * Kapatma (KAPATILDI) öncesi eksikler sunucunun `kapanis_icin_gerekenler`
 * listesinden gelir. Servis işi detayı da bu pencereyi kullanabilir.
 */
export function SlaKartiPenceresi({ soId, onKapat }: { soId: number | null; onKapat: () => void }) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const acik = soId != null;
  const kart = useQuery({
    queryKey: ["is-sla", soId],
    queryFn: () => operasyonApi.isSla(soId as number),
    enabled: acik,
  });
  const sozluk = useQuery({ queryKey: ["sla-sozluk"], queryFn: operasyonApi.sozluk, enabled: acik, staleTime: 300_000 });
  const k = kart.data;
  useEffect(() => {
    if (k)
      form.setFieldsValue({
        gecikme_nedeni: k.gecikme_nedeni,
        gecikme_aciklama: k.gecikme_aciklama,
        tekrar_ariza_teyit: k.tekrar_ariza.teyit,
      });
  }, [k, form]);
  const yazabilir =
    !!k &&
    k.status !== "IPTAL" &&
    (k.status === "KAPATILDI" ? yetkili("servis.kapat") : yetkili("servis.kapat") || yetkili("servis.tamamla"));
  const gecikmeGirilir = !!k && (k.sla.sonuc === "ASILDI" || k.sla.durum === "ASILDI");
  const teyitGirilir = !!k && k.tekrar_ariza.aday;
  const kaydet = useMutation({
    mutationFn: (v: { gecikme_nedeni?: string; gecikme_aciklama?: string; tekrar_ariza_teyit?: string }) => {
      const g: Record<string, unknown> = { version: k?.version };
      if (gecikmeGirilir) {
        g.gecikme_nedeni = v.gecikme_nedeni ?? null;
        g.gecikme_aciklama = v.gecikme_aciklama ?? null;
      }
      if (teyitGirilir) g.tekrar_ariza_teyit = v.tekrar_ariza_teyit ?? null;
      return operasyonApi.kapanisBilgisi(soId as number, g);
    },
    onSuccess: (yeni) => {
      message.success("Kapanış bilgisi kaydedildi");
      qc.setQueryData(["is-sla", soId], yeni);
      qc.invalidateQueries({ queryKey: ["operasyon-isler"] });
    },
    onError: (e: Error) => {
      message.error(e.message);
      qc.invalidateQueries({ queryKey: ["is-sla", soId] });
    },
  });
  const ad = (liste: { kod: string; ad: string }[] | undefined, kod: string | null | undefined) =>
    kod ? (liste?.find((x) => x.kod === kod)?.ad ?? kod) : "—";
  const bag = k?.tekrar_ariza.bagli_is;

  return (
    <Modal
      title={k ? `SLA kartı · ${k.so_no}` : "SLA kartı"}
      open={acik}
      onCancel={onKapat}
      onOk={yazabilir && (gecikmeGirilir || teyitGirilir) ? () => form.submit() : onKapat}
      okText={yazabilir && (gecikmeGirilir || teyitGirilir) ? "Kaydet" : "Kapat"}
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
      width={640}
    >
      {kart.isLoading || !k ? (
        <Spin />
      ) : (
        <>
          {k.kapanis_icin_gerekenler.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={`Kapatmadan önce girilmeli: ${k.kapanis_icin_gerekenler
                .map((e) => (e === "GECIKME_NEDENI" ? "gecikme nedeni" : "tekrar arıza teyidi"))
                .join(", ")}`}
            />
          )}
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Durum">
              <SlaEtiketi sla={k.sla} />
            </Descriptions.Item>
            <Descriptions.Item label="Çözüm hedefi">{zaman(k.sla.hedef_at)}</Descriptions.Item>
            {k.sla.ilk_hedef_at && k.sla.ilk_hedef_at !== k.sla.hedef_at && (
              <Descriptions.Item label="İlk hedef">{zaman(k.sla.ilk_hedef_at)}</Descriptions.Item>
            )}
            <Descriptions.Item label="Müdahale">
              {ad(sozluk.data?.mudahale_durumlari, k.sla.mudahale_durumu)}
              {k.sla.mudahale_hedef_at ? ` · hedef ${zaman(k.sla.mudahale_hedef_at)}` : ""}
              {k.sla.ilk_mudahale_at ? ` · ilk müdahale ${zaman(k.sla.ilk_mudahale_at)}` : ""}
            </Descriptions.Item>
            {!!k.sla.durdurulan_dk && (
              <Descriptions.Item label="İş beklemesiyle durdurulan">{sureMetni(k.sla.durdurulan_dk)}</Descriptions.Item>
            )}
            {k.sla.sonuc && <Descriptions.Item label="Sonuç (donmuş)">{k.sla.sonuc}</Descriptions.Item>}
            {k.tekrar_ariza.aday && (
              <Descriptions.Item label="Tekrar arıza adayı">
                {bag ? (
                  bag.kapsam_disi || bag.id == null ? (
                    <span>{bag.so_no}</span>
                  ) : (
                    <Link to={`/servis-isleri/${bag.id}`}>{bag.so_no}</Link>
                  )
                ) : (
                  "Önceki iş bağı yok"
                )}
              </Descriptions.Item>
            )}
          </Descriptions>
          {yazabilir && (gecikmeGirilir || teyitGirilir) && (
            <Form form={form} layout="vertical" style={{ marginTop: 12 }} onFinish={(v) => kaydet.mutate(v)}>
              {gecikmeGirilir && (
                <>
                  <Form.Item name="gecikme_nedeni" label="Gecikme nedeni">
                    <Select
                      allowClear
                      options={(sozluk.data?.gecikme_nedenleri ?? []).map((g) => ({ value: g.kod, label: g.ad }))}
                    />
                  </Form.Item>
                  <Form.Item
                    name="gecikme_aciklama"
                    label="Açıklama"
                    dependencies={["gecikme_nedeni"]}
                    rules={[
                      ({ getFieldValue }) => ({
                        required: getFieldValue("gecikme_nedeni") === "DIGER",
                        message: "'Diğer' nedeninde açıklama zorunlu",
                      }),
                      { max: 300, message: "En çok 300 karakter" },
                    ]}
                  >
                    <Input.TextArea rows={2} />
                  </Form.Item>
                </>
              )}
              {teyitGirilir && (
                <Form.Item name="tekrar_ariza_teyit" label="Tekrar arıza kök neden teyidi">
                  <Select
                    allowClear
                    options={(sozluk.data?.tekrar_ariza_teyitleri ?? []).map((g) => ({ value: g.kod, label: g.ad }))}
                  />
                </Form.Item>
              )}
            </Form>
          )}
          {!yazabilir && (gecikmeGirilir || teyitGirilir) && (
            <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
              {gecikmeGirilir && (
                <Descriptions.Item label="Gecikme nedeni">
                  {ad(sozluk.data?.gecikme_nedenleri, k.gecikme_nedeni)}
                  {k.gecikme_aciklama ? ` — ${k.gecikme_aciklama}` : ""}
                </Descriptions.Item>
              )}
              {teyitGirilir && (
                <Descriptions.Item label="Teyit">{ad(sozluk.data?.tekrar_ariza_teyitleri, k.tekrar_ariza.teyit)}</Descriptions.Item>
              )}
            </Descriptions>
          )}
        </>
      )}
    </Modal>
  );
}
