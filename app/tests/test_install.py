"""`agps install-addon`: the addon copied into the game's AddOns folder, and into every other one listed in
~/.agps-installs (a second install of the game, a private test server's; asked 2026-10-01)."""

from pathlib import Path
from types import SimpleNamespace

from azerothgps import cli


def test_install_goes_into_every_listed_addons_folder(tmp_path, monkeypatch):
    real = tmp_path / "World of Warcraft" / "_classic_beta_" / "Interface" / "AddOns"
    private = tmp_path / "Private" / "beta" / "Interface" / "AddOns"
    real.mkdir(parents=True)
    private.mkdir(parents=True)
    listed = tmp_path / "installs"
    listed.write_text(f"# the private server's\n\n{private}\n{tmp_path / 'missing'}\n{real}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "EXTRA_INSTALLS", listed)
    monkeypatch.setattr("azerothgps.hpa.refresh", lambda: None)  # (the terrain's blocks: not this test's)
    (private / "AzerothGPS").mkdir()
    (private / "AzerothGPS" / "Stale.lua").write_text("-- gone from the addon", encoding="utf-8")
    assert cli.extra_addons_dirs() == [private, tmp_path / "missing", real]
    rc = cli.cmd_install_addon(SimpleNamespace(wow_path=str(tmp_path / "World of Warcraft"), flavor="_classic_beta_", dev=False))
    assert rc == 0
    for addons in (real, private):
        assert (addons / "AzerothGPS" / "AzerothGPS.toc").is_file()
    assert not (private / "AzerothGPS" / "Stale.lua").exists()  # (a clean copy there too)


def test_no_list_means_just_the_game(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "EXTRA_INSTALLS", Path(tmp_path / "none"))
    assert cli.extra_addons_dirs() == []
