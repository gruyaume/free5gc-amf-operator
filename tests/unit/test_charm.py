# Copyright 2022 Guillaume Belanger
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import httpx
from lightkube.core.exceptions import ApiError
from lightkube.models.apps_v1 import StatefulSet, StatefulSetSpec
from lightkube.models.core_v1 import PodTemplateSpec
from lightkube.models.meta_v1 import LabelSelector, ObjectMeta
from ops import testing
from ops.model import ActiveStatus

from charm import Free5GcAMFOperatorCharm

testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.harness = testing.Harness(Free5GcAMFOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("lightkube.Client.patch")
    @patch("lightkube.Client.create")
    @patch("lightkube.Client.get")
    @patch("ops.model.Container.push")
    @patch("lightkube.core.client.GenericSyncClient")
    def test_given_can_connect_to_workload_container_when_config_changed_then_config_file_is_written(  # noqa: E501
        self, _, patch_push, patch_k8s_get, __, ___
    ):
        statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever name",
                template=PodTemplateSpec(metadata=ObjectMeta(annotations={"key": "value"})),
            )
        )
        patch_k8s_get.side_effect = [
            ApiError(response=httpx.Response(status_code=404, json={"key": "value"})),
            statefulset,
            statefulset,
        ]

        self.harness.set_can_connect(container="free5gc-amf", val=True)

        key_values = {"ngap-cidr": "1.2.3.4", "ngap-gateway": "5.6.7.8", "interface": "ens1"}
        self.harness.update_config(key_values=key_values)

        patch_push.assert_called_with(
            path="/free5gc/config/amfcfg.yaml",
            source="info:\n  version: 1.0.3\n  description: AMF initial local configuration\n\nconfiguration:\n  serviceNameList:\n    - namf-comm\n    - namf-evts\n    - namf-mt\n    - namf-loc\n    - namf-oam\n\n  ngapIpList:\n    - 10.100.50.249\n  sbi:\n    scheme: http\n    registerIPv4: amf-namf # IP used to register to NRF\n    bindingIPv4: 0.0.0.0  # IP used to bind the service\n    port: 80\n    tls:\n      key: config/TLS/amf.key\n      pem: config/TLS/amf.pem\n\n  nrfUri: http://nrf-nnrf:8000\n  amfName: AMF\n  serviceNameList:\n    - namf-comm\n    - namf-evts\n    - namf-mt\n    - namf-loc\n    - namf-oam\n  servedGuamiList:\n    - plmnId:\n        mcc: 208\n        mnc: 93\n      amfId: cafe00\n  supportTaiList:\n    - plmnId:\n        mcc: 208\n        mnc: 93\n      tac: 1\n  plmnSupportList:\n    - plmnId:\n        mcc: 208\n        mnc: 93\n      snssaiList:\n        - sst: 1\n          sd: 010203\n        - sst: 1\n          sd: 112233\n  supportDnnList:\n    - internet\n  security:\n    integrityOrder:\n      - NIA2\n    cipheringOrder:\n      - NEA0\n  networkName:\n    full: free5GC\n    short: free\n  locality: area1 # Name of the location where a set of AMF, SMF and UPFs are located\n  networkFeatureSupport5GS: # 5gs Network Feature Support IE, refer to TS 24.501\n    enable: true # append this IE in Registration accept or not\n    length: 1 # IE content length (uinteger, range: 1~3)\n    imsVoPS: 0 # IMS voice over PS session indicator (uinteger, range: 0~1)\n    emc: 0 # Emergency service support indicator for 3GPP access (uinteger, range: 0~3)\n    emf: 0 # Emergency service fallback indicator for 3GPP access (uinteger, range: 0~3)\n    iwkN26: 0 # Interworking without N26 interface indicator (uinteger, range: 0~1)\n    mpsi: 0 # MPS indicator (uinteger, range: 0~1)\n    emcN3: 0 # Emergency service support indicator for Non-3GPP access (uinteger, range: 0~1)\n    mcsi: 0 # MCS indicator (uinteger, range: 0~1)\n  t3502Value: 720\n  t3512Value: 3600\n  non3gppDeregistrationTimerValue: 3240\n  # retransmission timer for paging message\n  t3513:\n    enable: true     # true or false\n    expireTime: 6s   # default is 6 seconds\n    maxRetryTimes: 4 # the max number of retransmission\n  # retransmission timer for NAS Registration Accept message\n  t3522:\n    enable: true     # true or false\n    expireTime: 6s   # default is 6 seconds\n    maxRetryTimes: 4 # the max number of retransmission\n  # retransmission timer for NAS Registration Accept message\n  t3550:\n    enable: true     # true or false\n    expireTime: 6s   # default is 6 seconds\n    maxRetryTimes: 4 # the max number of retransmission\n  # retransmission timer for NAS Authentication Request/Security Mode Command message\n  t3560:\n    enable: true     # true or false\n    expireTime: 6s   # default is 6 seconds\n    maxRetryTimes: 4 # the max number of retransmission\n  # retransmission timer for NAS Notification message\n  t3565:\n    enable: true     # true or false\n    expireTime: 6s   # default is 6 seconds\n    maxRetryTimes: 4 # the max number of retransmission\n  t3570:\n    enable: true     # true or false\n    expireTime: 6s   # default is 6 seconds\n    maxRetryTimes: 4 # the max number of retransmission\n\nlogger:\n  AMF:\n    ReportCaller: false\n    debugLevel: info\n  Aper:\n    ReportCaller: false\n    debugLevel: info\n  FSM:\n    ReportCaller: false\n    debugLevel: info\n  NAS:\n    ReportCaller: false\n    debugLevel: info\n  NGAP:\n    ReportCaller: false\n    debugLevel: info",  # noqa: E501
        )

    @patch("ops.model.Container.exists")
    def test_given_config_file_is_written_when_pebble_ready_then_pebble_plan_is_applied(
        self, patch_exists
    ):
        patch_exists.return_value = True

        self.harness.container_pebble_ready(container_name="free5gc-amf")

        expected_plan = {
            "services": {
                "free5gc-amf": {
                    "override": "replace",
                    "command": "amf -c /free5gc/config/amfcfg.yaml",
                    "startup": "enabled",
                    "environment": {"GIN_MODE": "release"},
                }
            },
        }

        updated_plan = self.harness.get_container_pebble_plan("free5gc-amf").to_dict()

        self.assertEqual(expected_plan, updated_plan)

    @patch("ops.model.Container.exists")
    def test_given_config_file_is_written_when_pebble_ready_then_status_is_active(
        self, patch_exists
    ):
        patch_exists.return_value = True

        self.harness.container_pebble_ready("free5gc-amf")

        self.assertEqual(self.harness.model.unit.status, ActiveStatus())
