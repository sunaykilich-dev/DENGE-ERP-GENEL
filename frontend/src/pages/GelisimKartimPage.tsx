import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Spin } from "antd";

import { egitimApi } from "../api/egitim";
import { KisiKartiGorunumu } from "./EgitimKisiKarti";

/**
 * Gelişim Kartım (TS-157).
 *
 * Yalnız oturumdaki kişinin verisi (`GET /api/egitim/kendim`; kişi kimliği
 * parametre almaz). Kişi kendi gözleminin notunu, madde puanlarını ve aksiyon
 * planını görür (K12) ve "Gördüm" onayı verir — onay geri alınamaz.
 */
export default function GelisimKartimPage() {
  const kart = useQuery({ queryKey: ["egitim-kendim"], queryFn: egitimApi.kendim });
  return (
    <Card title="Gelişim Kartım">
      {kart.isLoading && <Spin />}
      {kart.error && <Alert type="error" title={(kart.error as Error).message} />}
      {kart.data && <KisiKartiGorunumu kart={kart.data} />}
    </Card>
  );
}
