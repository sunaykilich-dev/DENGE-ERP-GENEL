/**
 * Kiralama iadesinde barkodla kontrol (KARARLAR 2026-11-20 §2).
 *
 * Dönen telsizler/cihazlar okutulur, seri numarasız ek ekipman için gelen adet
 * girilir. "Karşılaştır" müşteride kalanlarla karşılaştırır; eksik ya da
 * yanlış cihaz varsa açıklama zorunludur. Kaydedilen sonuç kiralama
 * geçmişine yazılır ve iade satırlarını doldurur: okunan "İade alındı",
 * okunmayan "Müşteride" (not: açıklama). Kayıp kararını kullanıcı verir.
 */
import { useMutation } from "@tanstack/react-query";
import { Alert, App, Button, Card, Input, InputNumber, Space, Typography } from "antd";
import { useState } from "react";

import { kiralamaApi, type IadeKontrolSonucu, type KiralamaKarti } from "../api/kiralama";
import SeriOkutucu from "./SeriOkutucu";

export interface DoluSatir {
  sonuc?: string;
  adet?: number;
  depo_id?: number;
  not?: string;
}

export default function IadeOkutmaBolumu({
  k,
  onDoldur,
}: {
  k: KiralamaKarti;
  onDoldur: (satirlar: Record<number, DoluSatir>) => void;
}) {
  const { message } = App.useApp();
  const disarida = k.tahsisler.filter((t) => t.durum === "AKTIF" && t.musteride > 0);
  const beklenen = disarida.map((t) => t.seri).filter((x): x is string => !!x);
  const adetliler = disarida.filter((t) => !t.seri);
  const [okunan, setOkunan] = useState<string[]>([]);
  const [adetler, setAdetler] = useState<Record<number, number>>({});
  const [aciklama, setAciklama] = useState("");
  const [sonuc, setSonuc] = useState<IadeKontrolSonucu | null>(null);

  const istek = (kaydet: boolean) =>
    kiralamaApi.iadeKontrol(k.id, {
      okutulan_seriler: okunan,
      adetler: adetliler.map((t) => ({ tahsis_id: t.id, gelen: adetler[t.id] ?? 0 })),
      aciklama: aciklama.trim() || null,
      kaydet,
    });

  const doldur = (v: IadeKontrolSonucu) => {
    const depo = new Map(disarida.map((t) => [t.id, t.depo_id]));
    const not = aciklama.trim() || undefined;
    onDoldur(
      Object.fromEntries(
        v.satirlar.map((s) => [
          s.tahsis_id,
          s.oneri_sonuc === "IADE_ALINDI"
            ? { sonuc: "IADE_ALINDI", adet: s.seri ? undefined : s.gelen, depo_id: depo.get(s.tahsis_id) }
            : { sonuc: "MUSTERIDE", not },
        ]),
      ),
    );
  };

  const karsilastir = useMutation({
    mutationFn: () => istek(false),
    onSuccess: (v) => setSonuc(v),
    onError: (e: Error) => void message.error(e.message),
  });
  const kaydet = useMutation({
    mutationFn: () => istek(true),
    onSuccess: (v) => {
      message.success("İade kontrolü kaydedildi; satırlar dolduruldu");
      setSonuc(v);
      doldur(v);
    },
    onError: (e: Error) => void message.error(e.message),
  });

  if (!disarida.length) return null;
  const sorunlu = sonuc != null && !sonuc.tam;

  return (
    <Card size="small" title="Barkodla iade kontrolü">
      <Space orientation="vertical" style={{ width: "100%" }}>
        {beklenen.length > 0 && (
          <SeriOkutucu
            value={okunan}
            onChange={(v) => {
              setOkunan(v);
              setSonuc(null);
            }}
            beklenen={beklenen}
            placeholder="Dönen cihazın barkodunu okutun"
          />
        )}
        {adetliler.map((t) => (
          <Space key={t.id} wrap>
            <Typography.Text>
              {t.urun_kodu}: müşteride {t.musteride} adet, gelen
            </Typography.Text>
            <InputNumber
              min={0}
              max={t.musteride}
              precision={0}
              value={adetler[t.id]}
              onChange={(v) => {
                setAdetler((a) => ({ ...a, [t.id]: v ?? 0 }));
                setSonuc(null);
              }}
            />
          </Space>
        ))}
        {sonuc && (
          <Alert
            type={sonuc.tam ? "success" : "warning"}
            showIcon
            title={
              sonuc.tam
                ? "Bütün cihazlar geldi"
                : [
                    sonuc.eksik_seri ? `${sonuc.eksik_seri} seri cihaz okutulmadı` : null,
                    sonuc.eksik_adet ? `${sonuc.eksik_adet} adet ek ekipman eksik` : null,
                    sonuc.fazla.length ? `Bu kiralamaya ait olmayan: ${sonuc.fazla.join(", ")}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")
            }
          />
        )}
        {sorunlu && (
          <Input.TextArea
            rows={2}
            maxLength={500}
            placeholder="Eksik ya da yanlış cihaz için açıklama (zorunlu)"
            value={aciklama}
            onChange={(e) => setAciklama(e.target.value)}
          />
        )}
        <Space>
          <Button onClick={() => karsilastir.mutate()} loading={karsilastir.isPending}>
            Karşılaştır
          </Button>
          <Button
            type="primary"
            disabled={!sonuc || (sorunlu && !aciklama.trim())}
            loading={kaydet.isPending}
            onClick={() => kaydet.mutate()}
          >
            Kaydet ve satırları doldur
          </Button>
        </Space>
      </Space>
    </Card>
  );
}
