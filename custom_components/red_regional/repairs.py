"""Repair flows for Red Regional issues."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.components.repairs import FlowType, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def _description_placeholders(
    hass: HomeAssistant, issue_id: str
) -> dict[str, str] | None:
    """Return the placeholders of a live issue, if it still exists."""
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    if issue is None or not issue.translation_placeholders:
        return None
    return dict(issue.translation_placeholders)


class InvalidStopRepairFlow(RepairsFlow):
    """Hand an unknown stop to the reconfigure flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Enter the confirmation step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Open the entry reconfiguration, then close the issue."""
        if user_input is not None:
            assert self.data is not None
            entry_id = str(self.data["entry_id"])
            issue_id: str = self.issue_id
            reconfig = await self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry_id,
                },
            )
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return self.async_abort(
                reason="reconfigure",
                next_flow=(FlowType.CONFIG_FLOW, reconfig["flow_id"]),
            )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=_description_placeholders(
                self.hass, self.issue_id
            ),
        )


class BackendUnreachableRepairFlow(RepairsFlow):
    """Retry the backend by reloading the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Enter the confirmation step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Reload the entry after user confirmation."""
        if user_input is not None:
            assert self.data is not None
            await self.hass.config_entries.async_reload(str(self.data["entry_id"]))
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=_description_placeholders(
                self.hass, self.issue_id
            ),
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Route repair issues to their fix flows."""
    if issue_id.startswith("invalid_stop_"):
        return InvalidStopRepairFlow()
    if issue_id.startswith("backend_unreachable_"):
        return BackendUnreachableRepairFlow()
    raise data_entry_flow.UnknownHandler
