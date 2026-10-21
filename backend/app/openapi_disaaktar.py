"""OpenAPI şemasını dosyaya yazar (plan §D13, §3.4 "API OpenAPI ile belgelenir").

Üretimde `/api/openapi.json` KAPALI — API yüzeyini dışarı sergilememek için.
Bu yüzden şema derleme zamanında dosyaya çıkarılır: bayi paneli ya da bir
entegrasyon yazacak kişi dokümanı repodan alır, sunucudan değil.

    uv run python -m app.openapi_disaaktar            # docs/openapi.json
    uv run python -m app.openapi_disaaktar --kontrol  # dosya güncel mi
"""

import argparse
import json
import sys
from pathlib import Path

HEDEF = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def sema() -> dict:
    # Şema üretimi ENV'den bağımsız olmalı: prod yapılandırmasında docs
    # kapalı olduğu için `app.openapi()` şemayı yine üretir ama uygulamanın
    # kendisi açılış kontrolüne takılırdı.
    import os

    os.environ.setdefault("ENV", "dev")
    from app.main import create_app

    app = create_app()
    return app.openapi()


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="OpenAPI şemasını dışa aktar")
    ayristirici.add_argument(
        "--kontrol", action="store_true", help="Yazma; dosya güncel değilse 1 döndür"
    )
    args = ayristirici.parse_args(argv)

    metin = json.dumps(sema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.kontrol:
        if not HEDEF.exists() or HEDEF.read_text(encoding="utf-8") != metin:
            print(f"{HEDEF} guncel degil: 'make openapi' calistirin.", file=sys.stderr)
            return 1
        print(f"{HEDEF} guncel.")
        return 0

    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    HEDEF.write_text(metin, encoding="utf-8")
    yollar = len(json.loads(metin)["paths"])
    print(f"{HEDEF} yazildi ({yollar} yol).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
