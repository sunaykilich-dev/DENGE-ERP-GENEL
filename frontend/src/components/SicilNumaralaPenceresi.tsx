/**
 * Sicil numaralama (KARARLAR 2026-11-20 §8): sicili olmayan personel işe
 * giriş tarihine (şirket geçmişine) göre sırayla numaralanır. Önce önizleme,
 * onaylanınca uygulanır; var olan sicil değişmez.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Modal, Table, Typography } from "antd";
import dayjs from "dayjs";

import { api } from "../api/client";

interface Satir {
  id: number;
  ad: string;
  ise_giris_tarihi: string | null;
  sicil_no: string;
}

const numarala = (uygula: boolean) =>
  api.post<{ uygulandi: boolean; satirlar: Satir[] }>("/api/personel/sicil/numarala", { uygula });

export default function SicilNumaralaPenceresi({ acik, onKapat }: { acik: boolean; onKapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const onizleme = useQuery({ queryKey: ["sicil-onizleme"], queryFn: () => numarala(false), enabled: acik });
  const uygula = useMutation({
    mutationFn: () => numarala(true),
    onSuccess: (r) => {
      message.success(`${r.satirlar.length} personele sicil numarası verildi`);
      void qc.invalidateQueries({ queryKey: ["personel"] });
      onKapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const satirlar = onizleme.data?.satirlar ?? [];
  return (
    <Modal
      open={acik}
      title="Sicil numarala"
      width={640}
      onCancel={onKapat}
      onOk={() => uygula.mutate()}
      okText="Numaraları ver"
      okButtonProps={{ disabled: satirlar.length === 0 }}
      cancelText="Vazgeç"
      confirmLoading={uygula.isPending}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Sicili olmayan aktif personel işe giriş tarihine göre (en eskiden başlayarak) numaralanır. Var olan
        sicil numaraları değişmez. Yeni personelde sicil boş bırakılırsa sıradaki numara kendiliğinden verilir.
      </Typography.Paragraph>
      {onizleme.isError && <Alert type="error" showIcon title={(onizleme.error as Error).message} />}
      <Table<Satir>
        size="small"
        rowKey="id"
        loading={onizleme.isLoading}
        dataSource={satirlar}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        locale={{ emptyText: "Sicilsiz personel yok" }}
        columns={[
          { title: "Verilecek sicil", dataIndex: "sicil_no", width: 130, className: "mono" },
          { title: "Ad Soyad", dataIndex: "ad" },
          {
            title: "İşe giriş",
            dataIndex: "ise_giris_tarihi",
            width: 120,
            render: (x: string | null) => (x ? dayjs(x).format("DD.MM.YYYY") : "—"),
          },
        ]}
      />
    </Modal>
  );
}
