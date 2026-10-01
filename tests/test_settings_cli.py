"""Configuration, the command line, and the engine's handling of a failed render."""

import json

import pytest

from overset import cli, engine
from overset import render as render_mod
from overset import settings as settings_mod
from overset.settings import Settings


def test_defaults_skip_off_by_default_and_vision_rules():
    codes = Settings().active_codes()
    assert "OVS001" in codes and "OVS101" in codes
    assert "OVS301" not in codes and not any(c.startswith("OVS4") for c in codes)


def test_select_ignore_and_extend_follow_ruff():
    assert Settings(select=("OVS1",)).active_codes() == ["OVS101", "OVS102", "OVS103", "OVS104"]
    assert "OVS104" not in Settings(select=("OVS1",), ignore=("OVS104",)).active_codes()
    assert "OVS301" in Settings(extend_select=("OVS301",)).active_codes()


def test_no_render_drops_render_and_vision_rules():
    codes = Settings(render=False, vision=True).active_codes()
    assert not any(c in codes for c in ("OVS001", "OVS002", "OVS003", "OVS104", "OVS401"))


def test_vision_turns_on_every_vision_rule():
    assert sum(c.startswith("OVS4") for c in Settings(vision=True).active_codes()) == 6


def test_config_is_found_upward_and_paths_resolve_against_it(tmp_path):
    (tmp_path / "fonts").mkdir()
    (tmp_path / "overset.toml").write_text(
        'ignore = ["OVS203"]\nmin-font-pt = 12\npalette = ["#00C853"]\nfont-dirs = ["fonts"]\n')
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    s = settings_mod.load(start=deep)
    assert s.ignore == ("OVS203",) and s.min_font_pt == 12 and s.palette == ["00C853"]
    assert s.font_dirs == [(tmp_path / "fonts").resolve()]
    assert s.source == str(tmp_path / "overset.toml")


def test_pyproject_tool_table_is_read(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.overset]\nmax-words = 40\n')
    assert settings_mod.load(start=tmp_path).max_words == 40


def test_a_pyproject_without_the_table_is_not_a_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert settings_mod.find_config(tmp_path) is None or settings_mod.find_config(tmp_path).parent != tmp_path


def test_an_unknown_setting_is_an_error_not_ignored(tmp_path):
    with pytest.raises(ValueError, match="min_font"):
        settings_mod.from_mapping({"min_font": 12})


def test_list_rules_and_explain(capsys):
    assert cli.main(["--list-rules"]) == 0
    out = capsys.readouterr().out
    assert out.index("OVS001") < out.index("OVS101") < out.index("OVS401")
    assert cli.main(["--explain", "ovs002"]) == 0
    assert "Frames set to grow" in capsys.readouterr().out
    assert cli.main(["--explain", "OVS999"]) == 2


def test_usage_errors_exit_2(tmp_path, capsys):
    assert cli.main([]) == 2
    (tmp_path / "notes.md").write_text("x")
    assert cli.main([str(tmp_path / "notes.md")]) == 2
    (tmp_path / "broken.pptx").write_text("not a zip")
    assert cli.main([str(tmp_path / "broken.pptx"), "--no-render"]) == 2
    (tmp_path / "overset.toml").write_text("bogus = 1\n")
    assert cli.main([str(tmp_path / "broken.pptx")]) == 2
    assert "unknown setting" in capsys.readouterr().err


def test_findings_exit_1_and_clean_exits_0(builder, tmp_path, capsys):
    builder.text("Fine print", size=6)
    bad = builder.save(tmp_path / "bad.pptx")
    assert cli.main([str(bad), "--no-render"]) == 1
    out = capsys.readouterr().out
    assert "slide 1: OVS101 text at 6.0pt" in out and "1 finding in 1 deck (OVS101 ×1)." in out
    assert cli.main([str(bad), "--no-render", "--ignore", "OVS101"]) == 0
    assert "All clear: 1 deck checked." in capsys.readouterr().out


def test_json_output_is_one_object_per_deck(builder, tmp_path, capsys):
    builder.text("Fine print", size=6)
    bad = builder.save(tmp_path / "bad.pptx")
    assert cli.main([str(bad), "--no-render", "--format", "json"]) == 1
    (report,) = json.loads(capsys.readouterr().out)
    assert report["slides"] == 1 and report["rendered"] is False
    (f,) = report["findings"]
    assert (f["code"], f["slide"], f["label"], f["severity"]) == ("OVS101", 1, "slide 1", "warning")


def test_a_failed_render_skips_those_rules_and_says_so(builder, tmp_path, monkeypatch):
    def fail(*a, **kw):
        raise render_mod.RenderError("LibreOffice (soffice) is not installed")
    monkeypatch.setattr(render_mod, "render", fail)
    builder.text("Fine print", size=6)
    result = engine.lint(builder.save(tmp_path / "d.pptx"), Settings())
    assert [f.code for f in result.findings] == ["OVS101"], "structure rules still run"
    assert "OVS001" in result.skipped and not result.rendered
    assert "did not run: LibreOffice (soffice) is not installed" in result.notes[0]


def test_render_errors_are_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: None)
    with pytest.raises(render_mod.RenderError, match="not installed"):
        render_mod.to_pdf(tmp_path / "x.pptx", tmp_path)
    with pytest.raises(render_mod.RenderError, match="not installed"):
        render_mod._run(["definitely-not-a-binary-overset"])
    with pytest.raises(render_mod.RenderError, match="failed"):
        render_mod._run(["false"])


def test_font_dirs_become_a_fontconfig_file(tmp_path):
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    env = render_mod._font_env([fonts, tmp_path / "missing"], tmp_path)
    conf = (tmp_path / "fonts.conf").read_text()
    assert env["FONTCONFIG_FILE"] == str(tmp_path / "fonts.conf") and str(fonts.resolve()) in conf
    assert str(tmp_path / "missing") not in conf, "a folder that doesn't exist is dropped"
