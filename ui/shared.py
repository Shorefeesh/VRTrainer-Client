import tkinter as tk
from tkinter import ttk


class LabeledEntry(ttk.Frame):
    """A label with an entry field."""

    def __init__(self, master, text: str, **entry_kwargs) -> None:
        super().__init__(master)
        self.variable = tk.StringVar()

        self.label = ttk.Label(self, text=text)
        self.entry = ttk.Entry(self, textvariable=self.variable, **entry_kwargs)

        self.label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.entry.grid(row=0, column=1, sticky="ew")
        self.columnconfigure(1, weight=1)


class LabeledCombobox(ttk.Frame):
    """A label with a combobox."""

    def __init__(self, master, text: str, values=None, *, variable: tk.StringVar | None = None, **combo_kwargs) -> None:
        super().__init__(master)
        if values is None:
            values = []

        self.variable = variable or tk.StringVar()

        self.label = ttk.Label(self, text=text)
        self.combobox = ttk.Combobox(
            self,
            textvariable=self.variable,
            values=values,
            state=combo_kwargs.pop("state", "readonly"),
            **combo_kwargs,
        )

        self.label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.combobox.grid(row=0, column=1, sticky="ew")
        self.columnconfigure(1, weight=1)

    def set_values(self, values) -> None:
        self.combobox["values"] = values


class LabeledScale(ttk.Frame):
    """A label with a horizontal scale and live value indicator."""

    def __init__(
        self,
        master,
        text: str,
        *,
        from_: float = 0.0,
        to: float = 2.0,
        resolution: float = 0.05,
        initial: float = 1.0,
    ) -> None:
        super().__init__(master)

        self.variable = tk.DoubleVar(value=initial)

        label = ttk.Label(self, text=text)
        label.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.scale = ttk.Scale(
            self,
            variable=self.variable,
            from_=from_,
            to=to,
            orient="horizontal",
        )
        self.scale.grid(row=0, column=1, sticky="ew")

        self.value_label = ttk.Label(self, width=6, anchor="e")
        self.value_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.columnconfigure(1, weight=1)

        # Keep the displayed multiplier in sync.
        self.variable.trace_add("write", lambda *_: self._update_value_label())
        self._update_value_label()

        # Enforce step size manually because ttk.Scale does not support resolution.
        def _snap_to_resolution(value: float) -> float:
            step = resolution
            if step <= 0:
                return value
            snapped = round(value / step) * step
            return max(from_, min(to, snapped))

        def _on_move(*_) -> None:
            snapped = _snap_to_resolution(self.variable.get())
            if snapped != self.variable.get():
                self.variable.set(snapped)

        self.scale.configure(command=lambda _val: _on_move())

    def _update_value_label(self) -> None:
        self.value_label.configure(text=f"{self.variable.get():.2f}x")


class LabeledCheckbutton(ttk.Frame):
    """A single checkbutton with its own BooleanVar."""

    def __init__(self, master, text: str, **check_kwargs) -> None:
        super().__init__(master)
        self.variable = tk.BooleanVar()

        self.checkbutton = ttk.Checkbutton(
            self,
            text=text,
            variable=self.variable,
            **check_kwargs,
        )
        self.checkbutton.grid(row=0, column=0, sticky="w")


class StatusIndicator(ttk.Frame):
    """Label + status text, colour-coded."""

    def __init__(self, master, text: str, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._status_var = tk.StringVar(value="Unknown")

        self._label = ttk.Label(self, text=f"{text}:")
        self._value_label = ttk.Label(self, textvariable=self._status_var, foreground="grey")

        self._label.grid(row=0, column=0, sticky="w")
        self._value_label.grid(row=0, column=1, sticky="w", padx=(4, 0))

    def set_status(self, text: str, colour: str = "grey") -> None:
        self._status_var.set(text)
        self._value_label.configure(foreground=colour)


class ScrollableFrame(ttk.Frame):
    """A frame with a vertical scrollbar that appears when content is taller than the available space."""

    def __init__(self, master, *, min_height: int | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self._canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        if min_height is not None:
            self._canvas.configure(height=min_height)
        self._v_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.container = ttk.Frame(self._canvas)

        # Keep scroll region and width in sync with content.
        self._canvas_window = self._canvas.create_window((0, 0), window=self.container, anchor="nw")
        self.container.bind(
            "<Configure>",
            lambda event: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda event: self._canvas.itemconfigure(self._canvas_window, width=event.width),
        )

        self._canvas.configure(yscrollcommand=self._v_scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._v_scrollbar.pack(side="right", fill="y")


class TextBoxPanel(ttk.LabelFrame):
    """A labeled, scrollable text box for log-style content."""

    def __init__(
        self,
        master,
        title: str,
        *,
        height: int = 6,
        wrap: str = "word",
        max_lines: int | None = 300,
    ) -> None:
        super().__init__(master, text=title)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._text = tk.Text(self, height=height, wrap=wrap, state="disabled")
        self._text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._text.configure(yscrollcommand=scrollbar.set)

        self._max_lines = max_lines
        self._has_content = False

    def _set_text(self, text: str, *, is_placeholder: bool = False) -> None:
        self._has_content = False if is_placeholder else bool(text)
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        if text:
            if not text.endswith("\n"):
                text += "\n"
            self._text.insert("end", text)
        self._text.configure(state="disabled")

    def _append_text(self, text: str) -> None:
        if not text:
            return

        if not self._has_content:
            self._set_text("")
            self._has_content = True

        self._text.configure(state="normal")
        self._text.insert("end", text + "\n")

        if self._max_lines is not None:
            line_count = int(self._text.index("end-1c").split(".")[0])
            if line_count > self._max_lines:
                self._text.delete("1.0", f"{line_count - self._max_lines}.0")

        self._text.see("end")
        self._text.configure(state="disabled")
