from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_installer_scripts_are_plain_ascii():
    # Windows PowerShell 5.1 reads a script without a BOM in the old ANSI code
    # page, so any other character turns into garbage (a box-drawing range in a
    # regex once became an invalid pattern and crashed the setup window).
    for name in ("install.ps1", "Install TeddyClip.bat"):
        data = (ROOT / name).read_bytes()
        bad = sorted({b for b in data if b > 127})
        assert not bad, f"{name} has non-ASCII bytes {bad[:5]}; use escapes such as \u2500 instead"
