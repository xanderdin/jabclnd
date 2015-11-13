#
#   Copyright 2015 Alexander Pravdin <aledin@mail.ru>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

from twisted.application.service import ServiceMaker


__author__ = 'Alexander Pravdin <aledin@mail.ru>'


plugin_name = 'jabclnd'
module_name = plugin_name + '.tap'
description = 'A Jabber Client daemon'

jabclnd = ServiceMaker(plugin_name, module_name, description, plugin_name)
