from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
import time

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from interfaces.server import RemoteServerInterface
from logic.feature import FeatureContext, build_features_for_role
from logic.logging_utils import SessionLogManager


class Runtime:
    """Holds running trainer interfaces and feature instances."""

    _logger = logging.getLogger(__name__)

    def __init__(self) -> None:
        self.logs = SessionLogManager("runtime")

        self.osc: VRChatOSCInterface | None = None
        self.pishock: PiShockInterface | None = None
        self.whisper: WhisperInterface | None = None
        self.server = RemoteServerInterface()
        self.features: List[Any] = []
        self._status_cache: Dict[str, Dict[str, Any]] = {"trainer": {}, "pet": {}}
        self._local_role: str | None = None
        # Map pet client UUIDs to the trainer profile name currently assigned in-session.
        self._pet_profile_assignments: Dict[str, str] = {}
        # Cache the last config payload sent per pet so we can replay after reconnects.
        self._pet_profile_payloads: Dict[str, Dict[str, Any]] = {}

        self.server.start()

    def start_runtime(self, role: str, settings: dict, input_device: Optional[str]) -> None:
        self.stop_runtime()

        self.osc = VRChatOSCInterface(
            log_relevant_events=self.logs.get_logger("osc_relevant.log").log,
            role=role,
        )

        self.pishock = PiShockInterface(
            username=settings.get("pishock_username") or "",
            api_key=settings.get("pishock_api_key") or "",
            share_code=settings.get("pishock_share_code") or "",
            shocker_id=settings.get("pishock_shocker_id") or "",
            osc=self.osc,
        )

        self.whisper = WhisperInterface(input_device=input_device)

        if role == "pet":
            self.osc.start()
        self.pishock.start()
        self.whisper.start()

        self._replay_profile_configs()

        if role == "trainer":
            context = FeatureContext(
                role=role,
                osc=self.osc,
                pishock=self.pishock,
                whisper=self.whisper,
                server=self.server,
                log_manager=self.logs,
                config_provider=self.get_assigned_pet_configs,
            )
        else:
            context = FeatureContext(
                role=role,
                osc=self.osc,
                pishock=self.pishock,
                whisper=self.whisper,
                server=self.server,
                log_manager=self.logs,
            )

        self.features: List[Any] = build_features_for_role(role, context)

        for feature in self.features:
            if hasattr(feature, "start"):
                feature.start()

    def stop_runtime(self) -> None:
        # Stop features first so they no longer depend on interfaces.
        for feature in self.features:
            if hasattr(feature, "stop"):
                feature.stop()
        self.features = []

        if self.whisper is not None:
            self.whisper.stop()
        if self.pishock is not None:
            self.pishock.stop()
        if self.osc is not None:
            self.osc.stop()

        self.whisper = None
        self.pishock = None
        self.osc = None

    def get_osc_status(self) -> Optional[Dict[str, Any]]:
        """Return a snapshot of pet OSC diagnostics, if running."""
        if self.osc is None:
            return None
        return self.osc.get_status_snapshot()

    def get_pishock_status(self) -> Optional[Dict[str, Any]]:
        """Return a snapshot of pet PiShock status, if running."""
        if self.pishock is None:
            return None
        return {
            "connected": self.pishock.is_connected,
            "has_credentials": bool(getattr(self.pishock, "username", "") and getattr(self.pishock, "api_key", "")),
        }

    def get_whisper_log_text(self) -> str:
        """Return new Whisper transcript text for the UI log."""
        if self.whisper is None:
            return ""
        return self.whisper.get_new_text("ui_log")

    def get_whisper_backend(self) -> str:
        if self.whisper is None:
            return "Stopped"
        return self.whisper.get_backend_summary()

    def is_running(self) -> bool:
        return any((self.osc, self.pishock, self.whisper))

    def publish_runtime_status(self, role: str, status: Dict[str, str]) -> None:
        """Share the latest runtime status with the active session."""
        cache = self._status_cache.setdefault(role, {})
        last_payload = cache.get("payload")
        last_ts = float(cache.get("ts", 0.0))
        now = time.time()

        if status == last_payload and now - last_ts < 5.0:
            return

        try:
            self.server.send_status({"kind": "status", **status})
            cache["payload"] = dict(status)
            cache["ts"] = now
        except Exception:
            pass

    def _send_profile_config_to_pet(self, pet_client_id: str | list[str], settings: Dict[str, Any]) -> None:
        """Send a trainer profile payload to one or more pet clients via the server."""
        if not pet_client_id or not settings:
            return

        self.server.send_config(settings, target_client=pet_client_id)

    def _replay_profile_configs(self) -> None:
        """Resend cached profile payloads to currently assigned pets."""
        for pet_id, payload in list(self._pet_profile_payloads.items()):
            self.server.send_config(payload, target_client=pet_id)

    def _prune_missing_pet_assignments(self, session_pets: List[Dict[str, Any]]) -> None:
        """Drop assignments for pets that are no longer present in the session."""

        active_ids = {p.get("client_uuid") for p in session_pets if p.get("client_uuid")}
        for pet_id in list(self._pet_profile_assignments.keys()):
            if pet_id not in active_ids:
                self._pet_profile_assignments.pop(pet_id, None)
                self._pet_profile_payloads.pop(pet_id, None)

    def get_assigned_pet_configs(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of current per-pet profile payloads.

        Used by trainer-side features to route commands per pet using that pet's
        assigned configuration (names, words, feature flags, etc.).
        """

        return {pid: dict(payload) for pid, payload in self._pet_profile_payloads.items()}

    def assign_profile_to_pet(self, pet_client_id: str, profile_name: str | None, profile_settings: Dict[str, Any] | None) -> None:
        """Record a per-pet profile selection and push it to the pet."""
        if not profile_name:
            self._pet_profile_assignments.pop(pet_client_id, None)
            self._pet_profile_payloads.pop(pet_client_id, None)
            return

        self._pet_profile_assignments[pet_client_id] = profile_name
        if profile_settings:
            self._pet_profile_payloads[pet_client_id] = dict(profile_settings)
            self._send_profile_config_to_pet(pet_client_id, profile_settings)

    def notify_profile_updated(self, settings: Dict[str, Any]) -> None:
        """Propagate updates to any pets currently using the edited profile."""

        profile_name = settings.get("profile") or ""
        if not profile_name:
            return

        targets = [pid for pid, prof in self._pet_profile_assignments.items() if prof == profile_name]
        if not targets:
            return

        payload = dict(settings)
        for pet_id in targets:
            self._pet_profile_payloads[pet_id] = payload

        self._send_profile_config_to_pet(targets, payload)

    def rename_profile_assignment(self, old_name: str, new_name: str) -> None:
        """Keep in-session assignments in sync when a profile is renamed."""

        if not old_name or not new_name or old_name == new_name:
            return

        for pet_id, prof in list(self._pet_profile_assignments.items()):
            if prof == old_name:
                self._pet_profile_assignments[pet_id] = new_name
                payload = self._pet_profile_payloads.get(pet_id)
                if isinstance(payload, dict):
                    payload["profile"] = new_name
                    self._send_profile_config_to_pet(pet_id, payload)

    def remove_profile_assignments(self, profile_name: str) -> None:
        """Clear any assignments that reference a profile that was deleted."""

        for pet_id, prof in list(self._pet_profile_assignments.items()):
            if prof == profile_name:
                self._pet_profile_assignments.pop(pet_id, None)
                self._pet_profile_payloads.pop(pet_id, None)

    def set_server_username(self, username: str | None) -> dict:
        """Update the username used for server interactions."""
        if username is not None:
            self.server.set_username(username)
        return self.server.get_session_details()

    def get_server_username(self) -> str:
        """Return the username currently configured for server interactions."""
        return getattr(self.server, "_username", "") or ""

    def start_server_session(
        self,
        session_label: str | None = None,
        *,
        username: str | None = None,
        role: str = "trainer",
    ) -> dict:
        """Start a new server session (stub)."""
        if username is not None:
            self.server.set_username(username)
        self._local_role = role
        details = self.server.start_session(role=role, session_label=session_label)

        self._pet_profile_assignments.clear()
        self._pet_profile_payloads.clear()
        return details

    def join_server_session(
            self,
            session_id: str,
            *,
            username: str | None = None,
            role: str = "trainer"
        ) -> dict:
        """Join an existing server session (stub)."""
        if username is not None:
            self.server.set_username(username)
        self._local_role = role
        details = self.server.join_session(role=role, session_id=session_id)

        self._pet_profile_assignments.clear()
        self._pet_profile_payloads.clear()
        return details

    def leave_server_session(self) -> dict:
        """Leave the current server session (stub)."""
        details = self.server.leave_session()
        self._local_role = None

        self._pet_profile_assignments.clear()
        self._pet_profile_payloads.clear()
        return details

    def get_server_session_details(self) -> dict:
        """Return current session state for UI display."""
        details = self.server.get_session_details()

        if self._local_role:
            details["role"] = self._local_role

        if not details.get("session_id"):
            self._pet_profile_assignments.clear()
            self._pet_profile_payloads.clear()
            return details

        session_users = details.get("session_users") or []
        formatted_users: List[Dict[str, Any]] = []
        for user in session_users:
            role_raw = (user.get("role") or "").lower()
            role = "trainer" if role_raw == "leader" else "pet" if role_raw == "follower" else role_raw
            client_uuid = str(user.get("client_uuid") or user.get("id") or "")
            last_status = user.get("last_status") or {}
            username = user.get("username") or last_status.get("username") or ""
            label = username or (client_uuid[:8] if client_uuid else "(unknown)")

            formatted_users.append(
                {
                    "client_uuid": client_uuid,
                    "role": role,
                    "last_status": last_status,
                    "label": label,
                }
            )

        session_pets = [u for u in formatted_users if u.get("role") == "pet"]
        self._prune_missing_pet_assignments(session_pets)

        details["session_participants"] = formatted_users
        details["session_pets"] = session_pets
        details["pet_profile_assignments"] = dict(self._pet_profile_assignments)
        return details
