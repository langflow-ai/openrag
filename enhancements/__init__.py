"""OpenRAG enhancements package.

This directory is populated by enterprise / SaaS overlays via the
`git checkout --ours enhancements/ frontend/enhancements/` merge strategy.
In OSS it ships with a minimal set of additional connectors (IBM COS).
Strip the imports below to ship a bare OSS build.
"""

from connectors.base import BaseConnector

from .connectors.ibm_cos import IBMCOSConnector

ADDITIONAL_CONNECTORS: list[type[BaseConnector]] = [IBMCOSConnector]
