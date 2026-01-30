from logic import services
from .shared import TextBoxPanel


class EventLogPanel(TextBoxPanel):
    """Top-level event log that stays visible regardless of tab."""

    def __init__(self, master, *, list_height: int = 6) -> None:
        super().__init__(master, "Event log", height=list_height)

        self._refresh()

    def _set_events(self, events: list[str]) -> None:
        self._set_text("\n".join(events))

    def _refresh(self) -> None:
        try:
            details = services.get_server_session_details()
            events = details.get("events") or []
            self._set_events(events)
        except Exception:
            # UI should fail soft; missing events is not fatal.
            pass

        self.after(1500, self._refresh)


class WhisperLogPanel(TextBoxPanel):
    """Whisper transcript that follows the active runtime regardless of tab."""

    def __init__(self, master, *, list_height: int = 6) -> None:
        super().__init__(master, "Whisper log", height=list_height)

        self._current_role: str | None = None
        self._current_session: str | None = None

        self._reset_log(role=None)
        self._refresh()

    def _reset_log(self, role: str | None) -> None:
        if role:
            placeholder = f"Waiting for {role} whisper input..."
        else:
            placeholder = "Whisper transcript will appear after starting a trainer or pet runtime."
        self._set_text(placeholder, is_placeholder=True)

    def _refresh(self) -> None:
        try:
            details = services.get_server_session_details()
            role_raw = (details.get("role") or "").lower()
            role = role_raw if role_raw in {"trainer", "pet"} else None
            session_id = details.get("session_id") or None

            if role != self._current_role or session_id != self._current_session:
                self._current_role = role
                self._current_session = session_id
                self._reset_log(role)

            new_text = ""
            if role == "trainer" and services.is_running():
                new_text = services.get_whisper_log_text()
            elif role == "pet" and services.is_running():
                new_text = services.get_whisper_log_text()

            if new_text:
                self._append_text(new_text)
        except Exception:
            pass

        self.after(1000, self._refresh)
