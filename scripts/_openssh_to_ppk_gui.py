"""Convert OpenSSH private keys to native PuTTY .ppk via PuTTYgen GUI."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HOSTS = ["ln1", "ln2", "ln3", "sm"]
SSH_DIR = Path.home() / ".ssh"
PUTTYGEN = '"C:\\Program Files\\PuTTY\\puttygen.exe"'


def _ensure_pywinauto() -> None:
    try:
        from pywinauto import Application  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pywinauto", "-q"])


def _click_button(dlg, titles: tuple[str, ...]) -> bool:
    for title in titles:
        try:
            btn = dlg.child_window(title=title, class_name="Button")
            if btn.exists(timeout=0.5):
                btn.click()
                return True
        except Exception:
            pass
    try:
        for btn in dlg.descendants(class_name="Button"):
            text = (btn.window_text() or "").replace("&", "")
            if any(t.replace("&", "") == text for t in titles):
                btn.click()
                return True
    except Exception:
        pass
    return False


def _dismiss_modals(app, seconds: float = 2.5) -> None:
    end = time.time() + seconds
    while time.time() < end:
        for w in app.windows():
            title = w.window_text() or ""
            if title == "PuTTY Key Generator":
                continue
            if any(x in title for x in ("Warning", "Error", "PuTTYgen", "Confirm")):
                _click_button(w, ("Yes", "&Yes", "OK"))
                time.sleep(0.2)
        time.sleep(0.15)


def convert_one(name: str) -> None:
    from pywinauto import Application

    priv = SSH_DIR / name
    ppk = SSH_DIR / f"{name}.ppk"
    if not priv.exists():
        raise FileNotFoundError(priv)
    if ppk.exists():
        ppk.unlink()

    subprocess.run(["taskkill", "/IM", "puttygen.exe", "/F"], capture_output=True)
    time.sleep(0.3)

    app = Application(backend="win32").start(PUTTYGEN)
    time.sleep(1.0)
    win = app.window(title_re=".*PuTTY Key Generator.*")
    win.wait("visible", timeout=15)
    win.set_focus()

    win.menu_select("Conversions->Import key")
    time.sleep(0.5)

    dlg = app.window(title_re=".*Load private key.*")
    dlg.wait("visible", timeout=15)
    edits = [e for e in dlg.descendants(class_name="Edit")]
    edits[0].set_edit_text(str(priv))
    if not _click_button(dlg, ("Open", "&Open")):
        dlg.type_keys("{ENTER}")
    time.sleep(0.8)
    _dismiss_modals(app, 2.5)

    # Confirm import populated fingerprint
    fp = ""
    for c in win.descendants(class_name="Edit"):
        txt = c.window_text() or ""
        if "SHA256:" in txt:
            fp = txt
            break
    if not fp:
        raise RuntimeError(f"import did not load key for {name}")

    win.set_focus()
    if not _click_button(win, ("Save private key", "&Save private key")):
        raise RuntimeError("Save private key button not found")
    time.sleep(0.5)
    _dismiss_modals(app, 2.5)

    save = app.window(title_re=".*Save private key as.*|.*Save As.*")
    save.wait("visible", timeout=15)
    edits = [e for e in save.descendants(class_name="Edit")]
    edits[0].set_edit_text(str(ppk))
    if not _click_button(save, ("Save", "&Save")):
        save.type_keys("{ENTER}")
    time.sleep(0.6)
    _dismiss_modals(app, 2.0)

    deadline = time.time() + 10
    while time.time() < deadline:
        if ppk.exists() and ppk.stat().st_size > 50:
            break
        _dismiss_modals(app, 0.4)
        time.sleep(0.2)

    try:
        win.close()
    except Exception:
        subprocess.run(["taskkill", "/IM", "puttygen.exe", "/F"], capture_output=True)

    if not ppk.exists() or ppk.stat().st_size < 50:
        raise RuntimeError(f"PPK not created for {name}")

    head = ppk.read_text(encoding="ascii", errors="replace").splitlines()[0]
    print(f"OK: {ppk} ({ppk.stat().st_size} bytes) {head} | {fp}")


def main() -> int:
    _ensure_pywinauto()
    for name in HOSTS:
        print(f"=== Convert {name} ===")
        convert_one(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
