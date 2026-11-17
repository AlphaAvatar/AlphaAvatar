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
"""`alphaavatar upgrade`: a Linux installation to another build, switched to once.

``upgrade`` tells builds apart by their IDs, verifies and unpacks the target's package beside
the current version, prepares the default bundle's environment beside the current one with
setup's planning and installation (``alphaavatar.host.tools.setup``), then switches current.
"""
