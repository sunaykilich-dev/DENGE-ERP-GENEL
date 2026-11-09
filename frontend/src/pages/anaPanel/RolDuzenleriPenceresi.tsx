import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Empty, Modal, Popconfirm, Segmented, Select, Space, Tag } from "antd";
import { useEffect, useMemo, useState } from "react";

import {
  anaPanelDuzeniApi,
  DUZEN_SORGU_ANAHTARI,
  ekle,
  tasi,
  type Boyut,
  type DuzenOgesi,
  type RolDuzenYaniti,
} from "../../api/anaPanelDuzeni";

/**
 * Rol varsayılan düzenleri (KARARLAR 2026-11-09 S8.3, G7.3) — yalnız `panel.yonet`.
 *
 * Basit liste düzenleyicisi: rol seç → bileşenleri sırala, boyut seç, çıkar,
 * katalogdan ekle → Kaydet. Katalog sunucuda "rolün izni ∩ sizin izniniz" ile
 * süzülür. Kişisel düzeni olan kullanıcı kendi düzenini görmeye devam eder;
 * rol varsayılanı düzeni olmayanlara ve "Varsayılana dön" diyenlere geçer.
 */
export default function RolDuzenleriPenceresi({ acik, kapat }: { acik: boolean; kapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [rol, setRol] = useState<string>();
  const [taslak, setTaslak] = useState<DuzenOgesi[] | null>(null);

  const roller = useQuery({
    queryKey: ["ana-panel-rol-duzenleri"],
    queryFn: anaPanelDuzeniApi.roller,
    enabled: acik,
  });
  const duzen = useQuery({
    queryKey: ["ana-panel-rol-duzeni", rol],
    queryFn: () => anaPanelDuzeniApi.rolGetir(rol as string),
    enabled: acik && !!rol,
  });
  const veri = duzen.data;
  useEffect(() => setTaslak(veri ? veri.bilesenler.filter((o) => o.gorunur) : null), [veri]);

  const adlar = useMemo(() => new Map((veri?.katalog ?? []).map((k) => [k.kod, k])), [veri]);
  const eklenebilir = (veri?.katalog ?? []).filter((k) => !taslak?.some((o) => o.kod === k.kod));

  const bitti = (y: RolDuzenYaniti, mesaj: string) => {
    qc.setQueryData(["ana-panel-rol-duzeni", y.rol_kodu], y);
    qc.invalidateQueries({ queryKey: ["ana-panel-rol-duzenleri"] });
    qc.invalidateQueries({ queryKey: DUZEN_SORGU_ANAHTARI });
    message.success(mesaj);
  };
  const hata = (e: Error) => {
    message.error(e.message);
    duzen.refetch();
  };
  const kaydet = useMutation({
    mutationFn: () => anaPanelDuzeniApi.rolKaydet(rol as string, taslak ?? [], veri?.version ?? null),
    onSuccess: (y) => bitti(y, `${y.rol_adi} rolünün varsayılan paneli kaydedildi`),
    onError: hata,
  });
  const sifirla = useMutation({
    mutationFn: () => anaPanelDuzeniApi.rolSifirla(rol as string, veri?.version ?? null),
    onSuccess: (y) => bitti(y, `${y.rol_adi} rolü sistem varsayılanına döndü`),
    onError: hata,
  });

  const degistir = (i: number, yeni: Partial<DuzenOgesi>) =>
    setTaslak((t) => (t ? t.map((o, j) => (j === i ? { ...o, ...yeni } : o)) : t));

  return (
    <Modal
      title="Rol Varsayılan Panelleri"
      open={acik}
      onCancel={kapat}
      width={720}
      destroyOnHidden
      footer={
        <Space>
          <Popconfirm
            title="Bu rol sistem varsayılanına (bugünkü Ana Panel) dönsün mü?"
            okText="Evet"
            cancelText="Hayır"
            disabled={!veri || veri.kaynak !== "ROL"}
            onConfirm={() => sifirla.mutate()}
          >
            <Button disabled={!veri || veri.kaynak !== "ROL"} loading={sifirla.isPending}>
              Sistem Varsayılanına Dön
            </Button>
          </Popconfirm>
          <Button onClick={kapat}>Kapat</Button>
          <Button type="primary" disabled={!taslak} loading={kaydet.isPending} onClick={() => kaydet.mutate()}>
            Kaydet
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" style={{ width: "100%" }} size={10}>
        <Alert
          type="info"
          showIcon
          title="Kendi düzenini kaydetmemiş kullanıcılar bu rolün varsayılan panelini görür. Kişi yalnız izni olan bileşenleri görür."
        />
        <Select
          aria-label="Rol"
          placeholder="Rol seçin"
          style={{ width: "100%" }}
          value={rol}
          loading={roller.isLoading}
          showSearch={{ optionFilterProp: "label" }}
          options={(roller.data ?? []).map((r) => ({
            value: r.rol_kodu,
            label: `${r.rol_adi}${r.ozel ? " (özel)" : ""}`,
          }))}
          onChange={(v) => setRol(v)}
        />
        {veri && (
          <div>
            <Tag color={veri.kaynak === "ROL" ? "blue" : "default"}>
              {veri.kaynak === "ROL" ? "Bu rol için özel düzen" : "Sistem varsayılanı kullanılıyor"}
            </Tag>
          </div>
        )}
        {rol && taslak && (
          <>
            {taslak.length === 0 ? (
              <Empty description="Bu rolün panelinde bileşen yok" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <ol className="ap-rol-liste">
                {taslak.map((o, i) => (
                  <li key={o.kod}>
                    <span className="ad">{adlar.get(o.kod)?.ad ?? o.kod}</span>
                    <Segmented<Boyut>
                      size="small"
                      value={o.boyut}
                      options={[
                        { value: "DAR", label: "Dar" },
                        { value: "GENIS", label: "Geniş" },
                      ]}
                      onChange={(b) => degistir(i, { boyut: b })}
                    />
                    <Button
                      size="small"
                      type="text"
                      icon={<ArrowUpOutlined />}
                      aria-label="Yukarı taşı"
                      disabled={i === 0}
                      onClick={() => setTaslak((t) => (t ? tasi(t, i, i - 1) : t))}
                    />
                    <Button
                      size="small"
                      type="text"
                      icon={<ArrowDownOutlined />}
                      aria-label="Aşağı taşı"
                      disabled={i === taslak.length - 1}
                      onClick={() => setTaslak((t) => (t ? tasi(t, i, i + 1) : t))}
                    />
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      aria-label="Çıkar"
                      onClick={() => setTaslak((t) => (t ? t.filter((_, j) => j !== i) : t))}
                    />
                  </li>
                ))}
              </ol>
            )}
            <Select
              aria-label="Bileşen ekle"
              placeholder="Bileşen ekle…"
              style={{ width: "100%" }}
              value={null}
              disabled={eklenebilir.length === 0}
              options={eklenebilir.map((k) => ({ value: k.kod, label: `${k.ad} — ${k.grup}` }))}
              onChange={(kod: string) => {
                const k = adlar.get(kod);
                if (k) setTaslak((t) => ekle(t ?? [], k));
              }}
            />
          </>
        )}
      </Space>
    </Modal>
  );
}
