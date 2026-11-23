/**
 * Kiralama talebini onaylayıp teknik servis müdürüne yönlendirme
 * (KARARLAR 2026-11-20 §6). Bir kez yapılır; kiralama durumu değişmez,
 * müdür "Yönlendirmeler" ekranında birime yönlendirir.
 */
import { SendOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal } from "antd";
import { useState } from "react";

import { yonlendirmeApi } from "../api/yonlendirme";

export default function KiralamaTalepOnayi({ kiralamaId, onBitti }: { kiralamaId: number; onBitti: () => void }) {
  const { message } = App.useApp();
  const [acik, setAcik] = useState(false);
  const [form] = Form.useForm<{ sozlesme_detay?: string; not?: string }>();
  const gonder = useMutation({
    mutationFn: (v: { sozlesme_detay?: string; not?: string }) =>
      yonlendirmeApi.kiralamaTalepOnay(kiralamaId, {
        sozlesme_detay: v.sozlesme_detay?.trim() || null,
        not: v.not?.trim() || null,
      }),
    onSuccess: () => {
      message.success("Talep onaylandı; teknik servis müdürüne yönlendirildi");
      setAcik(false);
      onBitti();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  return (
    <>
      <Button icon={<SendOutlined />} onClick={() => setAcik(true)}>
        Talebi onayla, teknik servise yönlendir
      </Button>
      <Modal
        open={acik}
        title="Kiralama talebini onayla"
        onCancel={() => setAcik(false)}
        onOk={() => form.submit()}
        okText="Onayla ve yönlendir"
        cancelText="Vazgeç"
        confirmLoading={gonder.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => gonder.mutate(v)}>
          <Form.Item name="sozlesme_detay" label="Sözleşme / taahhüt ayrıntıları">
            <Input.TextArea rows={3} maxLength={4000} />
          </Form.Item>
          <Form.Item name="not" label="Not (isteğe bağlı)">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
