"""GitLab CI kuralları (deploy/GITLAB.md): canlı veri CI'a girmez, dağıtım elle."""

from pathlib import Path

import pytest
import yaml

KOK = Path(__file__).resolve().parents[3]
CI = KOK / ".gitlab-ci.yml"


@pytest.fixture(scope="module")
def ci() -> dict:
    if not CI.is_file():
        pytest.skip(".gitlab-ci.yml yok (yalnız backend)")
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_asamalar(ci: dict) -> None:
    assert ci["stages"] == ["denetim", "test", "paket", "dagitim"]


def test_dagitim_her_zaman_elle(ci: dict) -> None:
    for is_adi in ("dagit:prova", "dagit:canli"):
        kurallar = ci[is_adi]["rules"]
        assert kurallar and all(k.get("when") == "manual" for k in kurallar), is_adi
    # Canlı yalnız sürüm etiketinden.
    assert all("CI_COMMIT_TAG" in k["if"] for k in ci["dagit:canli"]["rules"])


def test_paket_dokum_tasimaz(ci: dict) -> None:
    betik = "\n".join(ci["paket"]["script"])
    assert "--yalniz-kod" in betik
    assert "test ! -e paket/denge-veritabani.sql.gz" in betik
    dagit = (KOK / "deploy" / "ci-dagit.sh").read_text(encoding="utf-8")
    assert "denge-veritabani.sql.gz" in dagit and "KVKK" in dagit


def test_ci_dagit_pakete_giriyor() -> None:
    uret = (KOK / "deploy" / "paket-uret.sh").read_text(encoding="utf-8")
    kur = (KOK / "deploy" / "kur.sh").read_text(encoding="utf-8")
    assert "ci-dagit.sh" in uret and "ci-dagit.sh" in kur
    assert (KOK / "deploy" / "GITLAB.md").is_file()
