"""Genel dosya eki.

Mobil saha uygulaması kapsam dışı olduğu için montaj kanıtı (fotoğraf, imzalı
form) ofis personeli tarafından sisteme yüklenecek — montaj noktası WhatsApp
veya e-posta ile gönderiyor. Bu yüzden ek mekanizması İŞ EMRİNE ÖZEL değil,
genel: cihaz, hesap, araç, teklif, sözleşme, hak ediş itirazı, gümrük evrakı
ve CE/TSE belgeleri de aynı tablodan beslenir.

Brief'te yalnızca `work_order_photos` ve `quote_versions.pdf_file` vardı;
ikisi de mobil uygulamaya bağlıydı ve o kapsamdan çıkınca evrak sistemin
tamamen dışında kalacaktı.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PkMixin

# Eklenebilecek kayıt türleri. Yeni modül gelince buraya eklenir.
EK_SAHIPLERI = (
    "accounts",
    "products",
    "devices",
    "vehicles",
    "sim_cards",
    "work_orders",
    "quotes",
    "contracts",
    "settlements",
    "import_files",
    # --- Teknik servis (plan §1.11). Yalnız tablosu VAR olanlar: kiralama ve
    # eğitim sahipleri kendi dalgalarında eklenir. Bu türlerin ek kapsamı
    # `services/teknik_servis/ek_kapsam.py` kayıt defterindedir (fail-closed).
    "service_orders",
    "service_equipment",
    "maintenance_contracts",
    "addresses",
)

# İşin niteliğine göre sınıflandırma — "eksik fotoğraf" kesintisi (brief §4.7)
# bu alana bakar.
EK_TURLERI = (
    "MONTAJ_FOTOGRAFI",
    "MONTAJ_FORMU",
    "IMZA",
    "RUHSAT",
    "SOZLESME",
    "VERGI_LEVHASI",
    "FATURA",
    "GUMRUK_EVRAKI",
    "UYGUNLUK_BELGESI",
    "ITIRAZ_YAZISI",
    # Ürün kartı: katalogdaki görsel ve satışın kullandığı belgeler.
    "URUN_GORSELI",
    "BROSUR",
    "TEKNIK_DOKUMAN",
    # Teknik servis (plan §1.11). Müşteri imzası mevcut `IMZA` ile tutulur;
    # ayrı `MUSTERI_IMZASI` türü açılmaz (iki ad aynı şeyi bölerdi).
    "SERVIS_ONCESI",
    "SERVIS_SONRASI",
    "SERVIS_FORMU",
    "BAKIM_FORMU",
    "GOZLEM_FOTOGRAFI",
    "DUZELTICI_KANIT",
    "SERTIFIKA",
    "DIGER",
)


class Attachment(Base, PkMixin):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_sahip", "entity", "entity_id"),
        CheckConstraint("size_bytes > 0", name="ck_attachments_boyut"),
    )

    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(30), server_default=text("'DIGER'"))

    file_name: Mapped[str] = mapped_column(String(255))
    # Diskteki göreli yol (FILES_DIR altında). Sunucuya çıkarken S3/MinIO'ya
    # geçilebilsin diye erişim `services/storage.py` arkasında.
    storage_path: Mapped[str] = mapped_column(String(400))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Aynı dosyanın iki kez yüklenmesini fark etmek için.
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)

    notes: Mapped[str | None] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
