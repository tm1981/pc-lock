from lockscreen import hotkey_to_tk


def test_hotkey_parsing():
    assert hotkey_to_tk('ctrl+alt+u') == ['<Control-Alt-KeyPress-u>', '<Control-Alt-KeyPress-U>']
    assert hotkey_to_tk('Ctrl+Shift+F12') == ['<Control-Shift-KeyPress-F12>']
