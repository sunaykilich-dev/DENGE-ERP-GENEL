import { BellOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Badge, Dropdown, Empty, Tag, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";

interface Uyari {
  kod: string;
  baslik: string;
  adet: number;
  yol: string;
  onem: "bilgi" | "uyari" | "kritik";
  aciklama: string;
}

interface Ozet {
  toplam: number;
  uyarilar: Uyari[];
}

const RENK: Record<string, string> = {
  kritik: "red",
  uyari: "orange",
  bilgi: "blue",
};

/**
 * Üst bardaki uyarı zili.
 *
 * Worker "taahhüdü bitecek hat=12" diye log'a yazıyordu ve orada kalıyordu;
 * uyarının değeri BİRİNE ULAŞMASINDA. Hat taahhüdü bitince aynı hattın aylık
 * maliyeti kat kat artıyor ve bunu ay sonunda faturadan öğrenmek pahalı.
 *
 * Sayılar sunucuda, kullanıcının İZİNLERİNE GÖRE hesaplanır: göremeyeceği
 * modülün uyarısını görmez, yoksa uyarı sayısının kendisi sızıntı olurdu.
 */
export default function UyariZili({ renk = "#556b82" }: { renk?: string } = {}) {
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["uyarilar"],
    queryFn: () => api.get<Ozet>("/api/raporlar/uyarilar"),
    // Zamana bağlı uyarılar; dakikada bir tazelemek yeterli, her tıklamada
    // yeniden hesaplamak gereksiz yük olurdu.
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const uyarilar = data?.uyarilar ?? [];
  const kritikVar = uyarilar.some((u) => u.onem === "kritik");

  const items = uyarilar.length
    ? uyarilar.map((u) => ({
        key: u.kod,
        label: (
          <div style={{ maxWidth: 320, paddingBlock: 4 }} onClick={() => navigate(u.yol)}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Tag color={RENK[u.onem]} style={{ marginInlineEnd: 0 }}>
                {u.adet}
              </Tag>
              <span style={{ fontWeight: 500 }}>{u.baslik}</span>
            </div>
            {u.aciklama && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {u.aciklama}
              </Typography.Text>
            )}
          </div>
        ),
      }))
    : [
        {
          key: "bos",
          label: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Bekleyen uyarı yok"
              style={{ margin: 8 }}
            />
          ),
        },
      ];

  return (
    <Dropdown menu={{ items }} trigger={["click"]} placement="bottomRight">
      {/* Rozet UYARI SAYISINI gösterir, kayıt toplamını değil: 22+39+39
          toplamı "99+" olarak çıkıyordu ve üç satırlık bir liste için
          yanıltıcıydı. Kayıt adedi her satırın kendi etiketinde. */}
      <Badge count={uyarilar.length} overflowCount={99} color={kritikVar ? "red" : "orange"}>
        {/* Rengi çağıran verir: koyu üst çubukta (Logo CRM kurgusu) açık renk. */}
        <BellOutlined style={{ color: renk, fontSize: 18, cursor: "pointer" }} aria-label="Uyarılar" />
      </Badge>
    </Dropdown>
  );
}
