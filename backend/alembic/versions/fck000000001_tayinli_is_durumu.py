"""Tayinli ama "yeni/tayin bekliyor" duran açık işler → PLANLANDI

2026-11-20 kullanıcı kararı: şef işi birine verdiğinde iş "verildi" sayılır
(`atama._durumu_esitle`: ekip gelince PLANLANDI = "TAYİN EDİLDİ"). Kural
yalnız bundan sonraki tayinlere uygulanır; bu geçiş daha önce tayin edilmiş
ama MUSTERI_TALEBI / PLANLAMADA / TEKRAR_ACILDI'da kalan açık işleri aynı
duruma getirir. Atölye işi kendi akışında olduğu için dışarıda kalır.

Her iş için geçmişe DURUM olayı yazılır (sistem, kullanıcısız); sürüm artar.
Downgrade bu geçişin olaylarından eski durumu geri yükler ve bunu da ayrı
bir DURUM olayıyla yazar (geçmiş yalnız eklenebilir); arada başka bir duruma
geçmiş iş olduğu gibi kalır.

Revision ID: fck000000001
Revises: fcj000000001
Create Date: 2026-11-20

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fck000000001"
down_revision: str | None = "fcj000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Olay `veri.kaynak` izi: tayin_gecisi_fck000000001 (downgrade bununla bulur).


def upgrade() -> None:
    op.execute(
        """
        WITH aday AS (
            SELECT so.id, so.status
            FROM service_orders so
            WHERE NOT so.is_deleted
              AND so.tur <> 'ATOLYE'
              AND so.status IN ('MUSTERI_TALEBI', 'PLANLAMADA', 'TEKRAR_ACILDI')
              AND EXISTS (
                  SELECT 1 FROM service_order_assignments a
                  WHERE a.service_order_id = so.id AND a.removed_at IS NULL
              )
        ), olay AS (
            INSERT INTO service_order_events
                (service_order_id, olay_turu, eski_durum, yeni_durum, ozet, veri, olusma_zamani)
            SELECT id, 'DURUM', status, 'PLANLANDI',
                   'Tayinli iş "Tayin edildi" durumuna alındı (sistem geçişi)',
                   jsonb_build_object('kaynak', 'tayin_gecisi_fck000000001'), now()
            FROM aday
        )
        UPDATE service_orders so
        SET status = 'PLANLANDI', version = so.version + 1, updated_at = now()
        FROM aday
        WHERE so.id = aday.id
        """
    )


def downgrade() -> None:
    # Geçmiş yalnız eklenebilir: geri dönüş de ayrı bir DURUM olayıyla yazılır.
    op.execute(
        """
        WITH geri AS (
            SELECT so.id, e.eski_durum
            FROM service_orders so
            JOIN service_order_events e ON e.service_order_id = so.id
            WHERE e.veri ->> 'kaynak' = 'tayin_gecisi_fck000000001' AND so.status = 'PLANLANDI'
        ), olay AS (
            INSERT INTO service_order_events
                (service_order_id, olay_turu, eski_durum, yeni_durum, ozet, veri, olusma_zamani)
            SELECT id, 'DURUM', 'PLANLANDI', eski_durum,
                   'Sistem geçişi geri alındı',
                   jsonb_build_object('kaynak', 'tayin_gecisi_fck000000001_geri'), now()
            FROM geri
        )
        UPDATE service_orders so
        SET status = geri.eski_durum, version = so.version + 1, updated_at = now()
        FROM geri
        WHERE so.id = geri.id
        """
    )
