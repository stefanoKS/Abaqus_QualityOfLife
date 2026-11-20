"""Product identity and backward-compatible configuration.

The rename to "Abaqus QOL" must not move existing installations. These tests pin
the documented precedence rules and prove that the legacy names still work.
"""

import pytest

from integrations import drawings
from integrations.abaqus import launcher
from services import store
from services.api.main import app

VARIABLES = (
    "SEAL_DATA",
    "ABAQUS_QOL_DATA",
    "SIMPLIFY_ABAQUS_LAUNCHER",
    "ABAQUS_QOL_LAUNCHER",
    "SEAL_ODA",
    "ABAQUS_QOL_ODA",
)


@pytest.fixture()
def clean_env(monkeypatch):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_default_data_directory_keeps_the_legacy_name(clean_env, tmp_path):
    clean_env.setenv("LOCALAPPDATA", str(tmp_path))
    assert store.root() == (tmp_path / "SimplifyAbaqus").resolve()
    assert store.root().is_dir()
    assert store.data_setting() == (store.ENV_DATA, "")


def test_new_data_alias_is_used_when_the_legacy_variable_is_absent(clean_env, tmp_path):
    target = tmp_path / "qol-data"
    clean_env.setenv("ABAQUS_QOL_DATA", str(target))
    assert store.data_setting() == (store.ENV_DATA_ALIAS, str(target))
    assert store.root() == target.resolve()


def test_legacy_data_variable_wins_over_the_alias(clean_env, tmp_path):
    legacy, alias = tmp_path / "legacy", tmp_path / "alias"
    clean_env.setenv("SEAL_DATA", str(legacy))
    clean_env.setenv("ABAQUS_QOL_DATA", str(alias))
    assert store.data_setting() == (store.ENV_DATA, str(legacy))
    assert store.root() == legacy.resolve()
    assert not alias.exists()


def test_seeded_data_is_not_duplicated_on_restart(clean_env, tmp_path):
    clean_env.setenv("ABAQUS_QOL_DATA", str(tmp_path / "store"))
    store.initialize()
    assert store.projects() == []
    store.save({"name": "Existing", "probes": []}, seed=True)
    store.save({"name": "Second seed", "probes": []}, seed=True)
    assert [project["name"] for project in store.projects()] == ["Existing"]


def test_launcher_alias_and_legacy_precedence(clean_env, tmp_path):
    legacy = tmp_path / "abq2024.bat"
    legacy.write_text("@echo off\n", encoding="utf-8")
    alias = tmp_path / "abq2024-alias.bat"
    alias.write_text("@echo off\n", encoding="utf-8")

    clean_env.setenv("ABAQUS_QOL_LAUNCHER", str(alias))
    assert launcher.launcher_setting() == (launcher.ENV_LAUNCHER_ALIAS, str(alias))
    assert launcher.configured_launcher() == alias.resolve()

    clean_env.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(legacy))
    assert launcher.launcher_setting() == (launcher.ENV_LAUNCHER, str(legacy))
    assert launcher.configured_launcher() == legacy.resolve()

    clean_env.delenv("SIMPLIFY_ABAQUS_LAUNCHER")
    clean_env.delenv("ABAQUS_QOL_LAUNCHER")
    with pytest.raises(ValueError, match="ABAQUS_QOL_LAUNCHER"):
        launcher.configured_launcher()


def test_oda_alias(clean_env, tmp_path):
    converter = tmp_path / "ODAFileConverter.exe"
    converter.write_text("", encoding="utf-8")
    clean_env.setenv("ABAQUS_QOL_ODA", str(converter))
    assert drawings.oda() == converter
    clean_env.setenv("SEAL_ODA", str(converter))
    assert drawings.oda() == converter


def test_api_documents_the_product_name():
    schema = app.openapi()
    assert schema["info"]["title"] == "Abaqus QOL"
    assert app.title == "Abaqus QOL"
