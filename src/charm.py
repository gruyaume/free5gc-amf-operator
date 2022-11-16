#!/usr/bin/env python3
# Copyright 2022 Guillaume Belanger
# See LICENSE file for licensing details.

"""Charmed operator for the free5GC AMF service."""

import json
import logging

from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from jinja2 import Environment, FileSystemLoader
from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.types import PatchType
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

from network_attachment_definition import NetworkAttachmentDefinition

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/free5gc/config"
CONFIG_FILE_NAME = "amfcfg.yaml"
NETWORK_ATTACHMENT_DEFINITION_NAME = "n2network-amf"


class Free5GcAMFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the free5gc amf operator."""

    def __init__(self, *args):
        super().__init__(*args)
        self._container_name = self._service_name = "free5gc-amf"
        self._container = self.unit.get_container(self._container_name)
        self.framework.observe(self.on.free5gc_amf_pebble_ready, self._on_free5gc_amf_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.remove, self._on_remove)
        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[ServicePort(name="http", port=80)],
        )

    def _on_config_changed(self, event) -> None:
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for container to be ready")
            event.defer()
            return
        self._write_config_file()
        if not self._network_attachment_definition_created:
            self._create_network_attachement_definition()
        if not self._annotation_added_to_statefulset:
            self._add_statefulset_pod_network_annotation()

    def _on_remove(self, event) -> None:
        self._delete_network_attachement_definition()

    @property
    def _network_attachment_definition_created(self) -> bool:
        client = Client()
        try:
            client.get(
                res=NetworkAttachmentDefinition,
                name=NETWORK_ATTACHMENT_DEFINITION_NAME,
                namespace=self.model.name,
            )
            logger.info(
                f"NetworkAttachmentDefinition {NETWORK_ATTACHMENT_DEFINITION_NAME} already created"
            )
            return True
        except ApiError as e:
            if e.status.reason == "NotFound":
                logger.info(
                    f"NetworkAttachmentDefinition {NETWORK_ATTACHMENT_DEFINITION_NAME} not yet created"
                )
                return False
        logger.info(
            f"Error when trying to retrieve NetworkAttachmentDefinition {NETWORK_ATTACHMENT_DEFINITION_NAME}"
        )
        return False

    @property
    def _annotation_added_to_statefulset(self) -> bool:
        client = Client()
        statefulset = client.get(res=StatefulSet, name=self.app.name, namespace=self.model.name)
        current_annotation = statefulset.spec.template.metadata.annotations
        if "k8s.v1.cni.cncf.io/networks" in current_annotation:
            logger.info("Multus annotation already added to statefulset")
            return True
        logger.info("ultus annotation not yet added to statefulset")
        return False

    def _create_network_attachement_definition(self) -> None:
        client = Client()
        nad_spec = {
            "cniVersion": "0.3.1",
            "plugins": [
                {
                    "type": "macvlan",
                    "capabilities": {"ips": True},
                    "master": self._config_interface,
                    "mode": "bridge",
                    "ipam": {
                        "type": "static",
                        "routes": [{"dst": "0.0.0.0/0", "gw": self._config_ngap_gateway}],
                    },
                },
                {"capabilities": {"mac": True}, "type": "tuning"},
            ],
        }
        nad = NetworkAttachmentDefinition(
            metadata=ObjectMeta(name=NETWORK_ATTACHMENT_DEFINITION_NAME),
            spec={"config": json.dumps(nad_spec)},
        )
        client.create(obj=nad, namespace=self.model.name)
        logger.info(f"NetworkAttachmentDefinition {NETWORK_ATTACHMENT_DEFINITION_NAME} created")

    def _delete_network_attachement_definition(self) -> None:
        client = Client()
        client.delete(
            res=NetworkAttachmentDefinition,
            name=NETWORK_ATTACHMENT_DEFINITION_NAME,
            namespace=self.model.name,
        )
        logger.info(f"NetworkAttachmentDefinition {NETWORK_ATTACHMENT_DEFINITION_NAME} deleted")

    def _add_statefulset_pod_network_annotation(self) -> None:
        multus_annotation = [
            {
                "name": NETWORK_ATTACHMENT_DEFINITION_NAME,
                "interface": "n2",
                "ips": self._config_ngap_cidr,
                "gateway": self._config_ngap_gateway,
            }
        ]
        client = Client()
        statefulset = client.get(res=StatefulSet, name=self.app.name, namespace=self.model.name)
        current_annotation = statefulset.spec.template.metadata.annotations
        current_annotation["k8s.v1.cni.cncf.io/networks"] = json.dumps(multus_annotation)
        client.patch(
            res=StatefulSet,
            name=self.app.name,
            obj=statefulset,
            patch_type=PatchType.MERGE,
            namespace=self.model.name,
        )
        logger.info(f"Multus annotation added to {self.app.name} Statefulset")

    def _write_config_file(self) -> None:
        jinja2_environment = Environment(loader=FileSystemLoader("src/templates/"))
        template = jinja2_environment.get_template("amfcfg.yaml.j2")
        content = template.render(ngap_ip_address=self._config_ngap_cidr.split("/")[0])
        self._container.push(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}", source=content)
        logger.info(f"Pushed {CONFIG_FILE_NAME} config file")

    @property
    def _config_file_is_written(self) -> bool:
        if not self._container.exists(f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            logger.info(f"Config file is not written: {CONFIG_FILE_NAME}")
            return False
        logger.info("Config file is written")
        return True

    @property
    def _config_ngap_cidr(self) -> str:
        return self.model.config["ngap-ip"]

    @property
    def _config_ngap_gateway(self) -> str:
        return self.model.config["ngap-gateway"]

    @property
    def _config_interface(self) -> str:
        return self.model.config["interface"]

    def _on_free5gc_amf_pebble_ready(self, event) -> None:
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for container to be ready")
            event.defer()
            return
        if not self._config_file_is_written:
            self.unit.status = WaitingStatus("Waiting for config file to be written")
            event.defer()
            return
        self._container.add_layer("free5gc-amf", self._pebble_layer, combine=True)
        self._container.replan()
        self.unit.status = ActiveStatus()

    @property
    def _pebble_layer(self) -> Layer:
        """Returns pebble layer for the charm.

        Returns:
            Layer: Pebble Layer
        """
        return Layer(
            {
                "summary": "free5gc-amf layer",
                "description": "pebble config layer for free5gc-amf",
                "services": {
                    "free5gc-amf": {
                        "override": "replace",
                        "startup": "enabled",
                        "command": f"./amf -c {BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}",
                        "environment": self._environment_variables,
                    },
                },
            }
        )

    @property
    def _environment_variables(self) -> dict:
        return {"GIN_MODE": "release"}


if __name__ == "__main__":
    main(Free5GcAMFOperatorCharm)
