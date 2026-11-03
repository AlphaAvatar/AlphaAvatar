# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Application configuration: select, load, compose, restore, inspect safely and create."""

from .application import ApplicationConfig
from .bundles import (
    ConfigReferenceError,
    ConfigSource,
    application_paths,
    format_failure,
    read_settings,
    select_configuration,
)
from .loader import (
    check_application_paths,
    load_application,
    restore_application,
    validate_application,
)
from .template import REQUIRED_ENVIRONMENT, CreatedBundle, create_bundle, render_bundle
from .view import describe_application, describe_error, describe_summary

__all__ = [
    "ApplicationConfig",
    "ConfigReferenceError",
    "ConfigSource",
    "CreatedBundle",
    "REQUIRED_ENVIRONMENT",
    "application_paths",
    "check_application_paths",
    "create_bundle",
    "describe_application",
    "describe_error",
    "describe_summary",
    "format_failure",
    "load_application",
    "read_settings",
    "render_bundle",
    "restore_application",
    "select_configuration",
    "validate_application",
]
