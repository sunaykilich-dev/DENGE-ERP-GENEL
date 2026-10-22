/**
 * Aktif Sayaç Bandı — açık sayaç, geçen süre, Bitir / Yanlış başlattım / Unuttum (TS-072/077).
 *
 * Yalnız `zaman.yaz` sahibinde çizilir ve istek atar; mobilite kullanıcısında
 * ne bant ne istek vardır. `["zaman-benim"]` sorgusu 30 sn'de bir tazelenir
 * (hafif uç; süre özeti hesaplanmaz). Geçen süre SUNUCU saatine göre sayılır
 * (`sunucuSimdi`): telefon saati kaymış olsa da gösterge doğru kalır.
 *
 * Bitir düğmesi atamaya bakmaz: sahibi kendi sayacını her zaman kapatabilir.
 * Uzun (≥10 sa ya da dünden kalmış) sayaçta kırmızı uyarı ve "Unuttum".
 */
import { FieldTimeOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { App, Button, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { FAALIYET_ADLARI, gecenSure, servisZaman, sunucuSimdi } from "../api/servisZaman";
import { UnuttumPenceresi, useCevrimici, useZamanTazele } from "./SayacDugmeleri";

export default function AktifSayacBandi() {
  const { yetkili } = useAuth();
  const izinli = yetkili("zaman.yaz");
  const { message } = App.useApp();
  const tazele = useZamanTazele();
  const cevrimici = useCevrimici();
  const [, setTik] = useState(0);
  const [unuttum, setUnuttum] = useState(false);

  const sayac = useQuery({
    queryKey: ["zaman-benim"],
    queryFn: () => servisZaman.benim(),
    enabled: izinli,
    refetchInterval: 30_000,
  });
  const acik = sayac.data?.acik_bolum ?? null;

  useEffect(() => {
    if (!acik) return;
    const t = window.setInterval(() => setTik((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [acik]);

  const islem = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => tazele(),
    onError: (e: Error) => {
      message.error(e.message);
      tazele();
    },
  });

  if (!izinli || !acik) return null;
  const uzun = sayac.data?.uzun_sayac ?? false;
  const geriBitis = sayac.data?.geri_alma_bitis;
  const geriAlinabilir = !!geriBitis && sunucuSimdi() < Date.parse(geriBitis);
  const kilitli = islem.isPending || !cevrimici;

  return (
    <div
      role="status"
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        marginBottom: 12,
        borderRadius: 6,
        background: uzun ? "#fff1f0" : "#e6f4ff",
        border: `1px solid ${uzun ? "#ffa39e" : "#91caff"}`,
      }}
    >
      <FieldTimeOutlined style={{ fontSize: 18 }} />
      <Space orientation="vertical" size={0} style={{ flex: "1 1 140px", minWidth: 0 }}>
        <Typography.Text strong ellipsis>
          {FAALIYET_ADLARI[acik.faaliyet]} ·{" "}
          <Link to={`/benim-islerim/${acik.service_order_id}`}>{acik.so_no}</Link>
        </Typography.Text>
        <Typography.Text style={{ fontVariantNumeric: "tabular-nums", fontSize: 18 }}>
          {gecenSure(acik.started_at)}
        </Typography.Text>
        {uzun && (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            Sayaç uzun süredir açık. Unuttuysanız gerçek bitişi girin.
          </Typography.Text>
        )}
        {!cevrimici && (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            Bağlantı yok — süreyi sonra elle girin.
          </Typography.Text>
        )}
      </Space>
      <Space wrap size={6}>
        <Button
          danger
          type="primary"
          style={{ minHeight: 44 }}
          disabled={kilitli}
          loading={islem.isPending}
          onClick={() =>
            islem.mutate(() => servisZaman.bitir(acik), {
              onSuccess: () => message.success("Sayaç bitirildi"),
            })
          }
        >
          Bitir
        </Button>
        {(uzun || !geriAlinabilir) && (
          <Button style={{ minHeight: 44 }} disabled={kilitli} onClick={() => setUnuttum(true)}>
            Unuttum
          </Button>
        )}
        {geriAlinabilir && (
          <Button
            type="link"
            danger
            disabled={kilitli}
            onClick={() =>
              islem.mutate(() => servisZaman.geriAl(acik), {
                onSuccess: () => message.success("Sayaç geri alındı"),
              })
            }
          >
            Yanlış başlattım
          </Button>
        )}
      </Space>
      <UnuttumPenceresi bolum={unuttum ? acik : null} onKapat={() => setUnuttum(false)} />
    </div>
  );
}
