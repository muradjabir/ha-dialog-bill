"""Sensor platform for Dialog Bill integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DialogDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _parse_date(val: Any) -> date | None:
    if not val:
        return None
    val_str = str(val).strip()
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True, kw_only=True)
class DialogSensorEntityDescription(SensorEntityDescription):
    """Describes a Dialog sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSOR_DESCRIPTIONS: tuple[DialogSensorEntityDescription, ...] = (
    DialogSensorEntityDescription(
        key="outstanding_balance",
        translation_key="outstanding_balance",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="LKR",
        suggested_display_precision=2,
        icon="mdi:cash",
        value_fn=lambda data: data.get("outstanding_balance"),
    ),
    DialogSensorEntityDescription(
        key="last_bill_amount",
        translation_key="last_bill_amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="LKR",
        suggested_display_precision=2,
        icon="mdi:file-document-outline",
        value_fn=lambda data: data.get("last_bill_amount"),
    ),
    DialogSensorEntityDescription(
        key="last_payment_amount",
        translation_key="last_payment_amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="LKR",
        suggested_display_precision=2,
        icon="mdi:cash-check",
        value_fn=lambda data: data.get("last_payment_amount"),
    ),
    DialogSensorEntityDescription(
        key="payment_due_date",
        translation_key="payment_due_date",
        device_class=SensorDeviceClass.DATE,
        icon="mdi:calendar-clock",
        value_fn=lambda data: _parse_date(data.get("payment_due_date")),
    ),
    DialogSensorEntityDescription(
        key="last_bill_date",
        translation_key="last_bill_date",
        device_class=SensorDeviceClass.DATE,
        icon="mdi:calendar-text",
        value_fn=lambda data: _parse_date(data.get("last_bill_date")),
    ),
    DialogSensorEntityDescription(
        key="status",
        translation_key="status",
        icon="mdi:signal",
        value_fn=lambda data: data.get("status"),
    ),
    DialogSensorEntityDescription(
        key="data_used",
        translation_key="data_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        icon="mdi:cloud-download",
        value_fn=lambda data: data.get("data_used_gb"),
    ),
    DialogSensorEntityDescription(
        key="data_remaining",
        translation_key="data_remaining",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        icon="mdi:database-arrow-down",
        value_fn=lambda data: data.get("data_remaining_gb"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Dialog sensors based on a config entry."""
    coordinator: DialogDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[DialogSensorEntity] = []
    if coordinator.data:
        for conn_num in coordinator.data:
            for desc in SENSOR_DESCRIPTIONS:
                # Add data usage sensors only if data is present or relevant
                if desc.key in ("data_used", "data_remaining"):
                    if coordinator.data[conn_num].get("data_total_gb") is None and coordinator.data[conn_num].get("data_used_gb") is None:
                        continue
                entities.append(
                    DialogSensorEntity(
                        coordinator=coordinator,
                        connection_number=conn_num,
                        description=desc,
                    )
                )

    async_add_entities(entities)


class DialogSensorEntity(
    CoordinatorEntity[DialogDataUpdateCoordinator], SensorEntity
):
    """Representation of a Dialog sensor."""

    entity_description: DialogSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DialogDataUpdateCoordinator,
        connection_number: str,
        description: DialogSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._connection_number = connection_number
        self._attr_unique_id = f"{DOMAIN}_{connection_number}_{description.key}"

        conn_data = coordinator.data.get(connection_number, {})
        nick = conn_data.get("nickName") or connection_number
        lob = conn_data.get("drupalLob") or conn_data.get("ddsLob") or "GSM"
        c_type = conn_data.get("connectionType", "POSTPAID")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, connection_number)},
            name=f"Dialog {nick} ({connection_number})",
            manufacturer="Dialog Axiata",
            model=f"Dialog {lob} {c_type}",
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        conn_data = self.coordinator.data.get(self._connection_number, {})
        return self.entity_description.value_fn(conn_data)
