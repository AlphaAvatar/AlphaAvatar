# Copyright 2025 AlphaAvatar project
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
"""This plugin's storage name: its directory in Avatar workspaces and in the model cache.

It is the plugin's own name, ``alphaavatar.plugins.<name>``, as its package and configuration
call it, so stored data stays put whatever the plugin registry calls the plugin.
"""

NAMESPACE = __name__.split(".")[2]
