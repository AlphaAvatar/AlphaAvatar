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
"""`alphaavatar cleanup`: what upgrades and setups leave in a Linux installation, removed.

``cleanup`` surveys the prefix's envs/ and versions/: the environments current does not run,
then the base packages no kept environment is over, go; whatever it cannot tell the installer
made stays, with why. It uses the installation's layout and lock
(``alphaavatar.host.tools.setup``), and changes nothing outside those two directories.
"""
