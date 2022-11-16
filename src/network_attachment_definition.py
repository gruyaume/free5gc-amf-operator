# Copyright 2022 Guillaume Belanger
# See LICENSE file for licensing details.

"""NetworkAttachmentDefinition."""

from lightkube.generic_resource import create_namespaced_resource

NetworkAttachmentDefinition = create_namespaced_resource(
    group="k8s.cni.cncf.io",
    version="v1",
    kind="NetworkAttachmentDefinition",
    plural="network-attachment-definitions",
)
