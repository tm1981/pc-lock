"""
Password dialogs for PC-Lock UI.
"""
import customtkinter as ctk


class PasswordDialog(ctk.CTkToplevel):
    """Modern password input dialog."""

    def __init__(self, parent, title: str, prompt: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x170")
        self.resizable(False, False)
        self.result = None

        # Center on parent
        self.transient(parent)
        self.grab_set()

        # Widgets
        ctk.CTkLabel(self, text=prompt, font=ctk.CTkFont(size=14)).pack(pady=(20, 10))

        self.entry = ctk.CTkEntry(self, width=320, show="•", font=ctk.CTkFont(size=14))
        self.entry.pack(pady=10)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self._on_ok())

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=15)

        ctk.CTkButton(btn_frame, text="OK", width=120, command=self._on_ok).pack(side="left", padx=20)
        ctk.CTkButton(btn_frame, text="Cancel", width=120, fg_color="gray40",
                      hover_color="gray30", command=self._on_cancel).pack(side="left", padx=20)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window()

    def _on_ok(self):
        self.result = self.entry.get()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


def ask_password(parent, title: str, prompt: str) -> str | None:
    """Show password dialog and return input or None."""
    dialog = PasswordDialog(parent, title, prompt)
    return dialog.result
