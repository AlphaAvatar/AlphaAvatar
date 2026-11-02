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
"""Application configuration: load, validate, restore, inspect safely and create templates."""

from .application import ApplicationConfig
from .loader import (
    check_application_paths,
    load_application,
    restore_application,
    validate_application,
)
from .template import REQUIRED_ENVIRONMENT, render_template, write_template
from .view import describe_application, describe_error, describe_summary

__all__ = [
    "ApplicationConfig",
    "REQUIRED_ENVIRONMENT",
    "check_application_paths",
    "describe_application",
    "describe_error",
    "describe_summary",
    "load_application",
    "render_template",
    "restore_application",
    "validate_application",
    "write_template",
]
