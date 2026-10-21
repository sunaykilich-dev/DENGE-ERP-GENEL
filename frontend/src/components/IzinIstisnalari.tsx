import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Input, Select, Space, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { api } from "../api/client";

interface Izin {
  kod: string;
  modul: string;
  aciklama: string;
}

interface Istisna {
  permission_code: string;
  allow: boolean;
  gerekce: string;
}

/**
 * Kullanıcıya ÖZEL izin istisnaları — rolün üstüne ekler ya da ondan çıkarır.
 *
 * Rol omurgadır; bu istisnadır. Aynı roldeki iki kişinin farklı şey görmesi
 * altı ay sonra kimsenin hatırlamadığı bir soruya dönüşür, bu yüzden her
 * istisna GEREKÇE ister ve listede "rolünden farklı" olarak görünür.
 *
 * Kaydetmek kullanıcının açık oturumlarını düşürür: eski yetkiyle açılmış
 * bir oturum yeni kısıtı görmezdi.
 */
export default function IzinIstisnalari({
  userId,
  kendisiMi,
}: {
  userId: number;
  kendisiMi: boolean;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [satirlar, setSatirlar] = useState<Istisna[]>([]);
  const [yeniKod, setYeniKod] = useState<string>();

  const katalog = useQuery({
    queryKey: ["izin-katalogu"],
    queryFn: () => api.get<Izin[]>("/api/izinler"),
  });
  const mevcut = useQuery({
    queryKey: ["kullanici-izinleri", userId],
    queryFn: () => api.get<Istisna[]>(`/api/kullanicilar/${userId}/izinler`),
  });

  useEffect(() => {
    if (mevcut.data) setSatirlar(mevcut.data);
  }, [mevcut.data]);

  const kaydet = useMutation({
    mutationFn: (v: Istisna[]) => api.put(`/api/kullanicilar/${userId}/izinler`, v),
    onSuccess: () => {
      message.success("İstisnalar kaydedildi; kullanıcının oturumları düştü");
      void qc.invalidateQueries({ queryKey: ["kullanici-izinleri", userId] });
      // Üstteki "erişebileceği sayfalar" paneli bu kişinin etkin yetkisini
      // gösteriyor; istisna değişince orası da tazelenmeli.
      void qc.invalidateQueries({ queryKey: ["kullanici-yetkileri", userId] });
      void qc.invalidateQueries({ queryKey: ["kullanicilar"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  if (kendisiMi) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Kendi izinlerinizi değiştiremezsiniz — yönetici kendini kilitleyebilir ya da
        sessizce yetkisini yükseltebilirdi.
      </Typography.Text>
    );
  }

  const ad = (kod: string) => katalog.data?.find((i) => i.kod === kod)?.aciklama ?? kod;
  const eklenebilir = (katalog.data ?? []).filter(
    (i) => !satirlar.some((s) => s.permission_code === i.kod),
  );

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Rolün üstüne istisna. Gerekli değilse boş bırakın — aynı roldeki kişilerin aynı
        şeyi görmesi, sonradan "bu neden böyle" sorusunu doğurmaz.
      </Typography.Text>

      <Space.Compact style={{ width: "100%" }}>
        <Select
          showSearch
          value={yeniKod}
          onChange={setYeniKod}
          style={{ flex: 1 }}
          placeholder="İzin seçin"
          optionFilterProp="label"
          options={eklenebilir.map((i) => ({
            value: i.kod,
            label: `${i.modul} · ${i.aciklama}`,
          }))}
        />
        <Button
          disabled={!yeniKod}
          onClick={() => {
            if (!yeniKod) return;
            setSatirlar((o) => [
              ...o,
              { permission_code: yeniKod, allow: true, gerekce: "" },
            ]);
            setYeniKod(undefined);
          }}
        >
          Ekle
        </Button>
      </Space.Compact>

      {satirlar.length > 0 && (
        <Table
          rowKey="permission_code"
          size="small"
          pagination={false}
          dataSource={satirlar}
          columns={[
            {
              title: "İzin",
              render: (_: unknown, s: Istisna) => (
                <span style={{ fontSize: 12 }}>{ad(s.permission_code)}</span>
              ),
            },
            {
              title: "Yön",
              width: 130,
              render: (_: unknown, s: Istisna) => (
                <Select
                  size="small"
                  value={s.allow}
                  style={{ width: 118 }}
                  onChange={(v) =>
                    setSatirlar((o) =>
                      o.map((x) =>
                        x.permission_code === s.permission_code ? { ...x, allow: v } : x,
                      ),
                    )
                  }
                  options={[
                    { value: true, label: "Ek olarak ver" },
                    { value: false, label: "Geri al" },
                  ]}
                />
              ),
            },
            {
              title: "Gerekçe",
              render: (_: unknown, s: Istisna) => (
                <Input
                  size="small"
                  value={s.gerekce}
                  placeholder="En az 5 karakter — neden istisna?"
                  onChange={(e) =>
                    setSatirlar((o) =>
                      o.map((x) =>
                        x.permission_code === s.permission_code
                          ? { ...x, gerekce: e.target.value }
                          : x,
                      ),
                    )
                  }
                />
              ),
            },
            {
              title: "",
              width: 40,
              render: (_: unknown, s: Istisna) => (
                <Button
                  size="small"
                  type="text"
                  danger
                  onClick={() =>
                    setSatirlar((o) =>
                      o.filter((x) => x.permission_code !== s.permission_code),
                    )
                  }
                >
                  ×
                </Button>
              ),
            },
          ]}
        />
      )}

      <Space>
        <Button
          size="small"
          type="primary"
          loading={kaydet.isPending}
          disabled={satirlar.some((s) => s.gerekce.trim().length < 5)}
          onClick={() => kaydet.mutate(satirlar)}
        >
          İstisnaları kaydet
        </Button>
        {satirlar.length > 0 && <Tag color="orange">rolünden farklı {satirlar.length} izin</Tag>}
      </Space>
    </Space>
  );
}
