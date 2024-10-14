from __future__ import annotations

import re
from typing import TYPE_CHECKING

import websocket
from cloudshell.cli.session.session_exceptions import SessionReadTimeout
from cloudshell.cli.session.telnet_session import TelnetSession

from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler


if TYPE_CHECKING:
    from logging import Logger

    from cloudshell.cli.types import T_ON_SESSION_START, T_TIMEOUT


ansi_escape = re.compile(r'''
    \x1B  # ESC
    (?:   # 7-bit C1 Fe (except CSI)
        [@-Z\\-_]
    |     # or [ for CSI, followed by a control sequence
        \[
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    )
''', re.VERBOSE)


class WebSocketSession(TelnetSession):
    def __init__(
            self,
            host: str,
            username: str,
            password: str,
            node: str,
            port: int | None = None,
            on_session_start: T_ON_SESSION_START | None = None,
            proxmox_handler: ProxmoxHandler = None,
            *args,
            **kwargs,
    ):
        super().__init__(
            host,
            username,
            password,
            port=port,
            on_session_start=on_session_start,
            *args,
            **kwargs,
        )
        self.proxmox_handler = proxmox_handler
        self._node = node

    def _initialize_session(
            self,
            prompt: str,
            logger: Logger,
            proxmox_handler: ProxmoxHandler = None
    ) -> None:
        if not proxmox_handler and not self.proxmox_handler:
            raise ValueError("Proxmox handler is not provided")
        if proxmox_handler:
            self.proxmox_handler = proxmox_handler
        self._handler = self.proxmox_handler.get_websocket(self._node)

        handshake = f"{self.username}:{self.proxmox_handler.auth_ticket}\n"

        self._handler.send_bytes(str.encode(handshake))

    def _connect_actions(self, prompt: str, logger: Logger) -> None:
        self.hardware_expect(
            self._connect_command,
            expected_string=prompt,
            timeout=self._timeout,
            logger=logger,
            action_map=self._connect_action_map,
        )
        self._on_session_start(logger)

    def _send(self, command: str, logger: Logger) -> None:
        """Send message / command to device."""
        message_cmd = "0:" + str(len(command)) + ":" + command
        self._handler.send_bytes(str.encode(message_cmd))

    def _set_timeout(self, timeout: T_TIMEOUT) -> None:
        pass

    def _read_byte_data(self) -> bytes:
        try:
            return self._handler.recv()
        except websocket.WebSocketTimeoutException:
            raise SessionReadTimeout()

    def _read_str_data(self) -> str:
        byte_data = b""
        for _ in range(5):
            new_data = self._read_byte_data()

            if not new_data:
                str_data = new_data.decode()
                break

            byte_data += new_data
            try:
                str_data = byte_data.decode()
            except UnicodeDecodeError:
                continue
            else:
                break
        else:
            str_data = byte_data.decode()
        return ansi_escape.sub('', str_data)

    def disconnect(self) -> None:
        if self._handler:
            self._handler.close()
            self._active = False
