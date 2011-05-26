# configscreen.py - Copyright (C) 2009 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

from snack import *
from halworker import HALWorker
from libvirtworker import *
import traceback

BACK_BUTTON   = "back"
NEXT_BUTTON   = "next"
CANCEL_BUTTON = "cancel"
FINISH_BUTTON = "finish"

class ConfigScreen:
    '''Enables the creation of navigable, multi-paged configuration screens.'''

    def __init__(self, title):
        self.__title = title
        self.__current_page = 1
        self.__finished = False
        self.__hal = HALWorker()
        self.__libvirt = LibvirtWorker()
        self.__vm_config = VirtManagerConfig()

    def get_title(self):
        return self.__title

    def get_hal(self):
        return self.__hal

    def get_libvirt(self):
        return self.__libvirt

    def get_virt_manager_config(self):
        return self.__vm_config

    def set_finished(self):
        self.__finished = True

    def get_elements_for_page(self, screen, page):
        return []

    def page_has_next(self, page):
        return False

    def page_has_finish(self, page):
        return False

    def get_back_page(self, page):
        if page > 1: return page - 1
        return page

    def go_back(self):
        self.__current_page = self.get_back_page(self.__current_page)

    def get_next_page(self, page):
        return page + 1

    def go_next(self):
        self.__current_page = self.get_next_page(self.__current_page)

    def validate_input(self, page, errors):
        return True

    def process_input(self, page):
        return

    def get_page_list(self):
        return []

    def get_current_page(self):
        0

    def start(self):
        active = True
        while active and (self.__finished == False):
            screen = SnackScreen()
            elements = self.get_elements_for_page(screen, self.__current_page)
            # TODO: need to set the form height to the number of elements on the page
            gridform = GridForm(screen, self.get_title(), 2, 2)

            # Here you would put the list of elements
            # and programmatically set the indicator as
            # they're rendered
            pages = self.get_page_list()
            if len(pages) > 0:
                leftmenu = Grid(2, len(pages))
                current_element = 0
                for page in pages:
                    leftmenu.setField(Label(page), 0, current_element, anchorLeft = 1)
                    indicator = " "
                    if current_element == self.__current_page - 1:
                        indicator = "<-"
                    leftmenu.setField(Label(indicator), 1, current_element)
                    current_element += 1
                gridform.add(leftmenu, 0, 0, anchorTop = 1, padding = (3, 0, 3, 0))

            content = Grid(1, len(elements) + 1)
            current_element = 0
            for element in elements:
                content.setField(element, 0, current_element)
                current_element += 1
            # create the navigation buttons
            buttons = []
            if self.__current_page > 1: buttons.append(["Back", BACK_BUTTON, "F11"])
            if self.page_has_next(self.__current_page): buttons.append(["Next", NEXT_BUTTON, "F12"])
            if self.page_has_finish(self.__current_page): buttons.append(["Finish", FINISH_BUTTON, "F10"])
            buttons.append(["Cancel", CANCEL_BUTTON, "ESC"])
            buttonbar = ButtonBar(screen, buttons)
            content.setField(buttonbar, 0, current_element, growx = 1)
            gridform.add(content, 1, 0, anchorTop = 1)
            current_element += 1
            try:
                result = gridform.runOnce()
                pressed = buttonbar.buttonPressed(result)
                if pressed == BACK_BUTTON:
                    self.go_back()
                elif pressed == NEXT_BUTTON or pressed == FINISH_BUTTON:
                    errors = []
                    if self.validate_input(self.__current_page, errors):
                        self.process_input(self.__current_page)
                        self.go_next()
                    else:
                        error_text = ""
                        for error in errors:
                            error_text += "%s\n" % error
                            ButtonChoiceWindow(screen,
                                               "There Were Errors",
                                               error_text,
                                               buttons = ["OK"])
                elif pressed == CANCEL_BUTTON:
                    active = False
            except Exception, error:
                ButtonChoiceWindow(screen,
                                   "An Exception Has Occurred",
                                   str(error) + "\n" + traceback.format_exc(),
                                   buttons = ["OK"])
            screen.popWindow()
            screen.finish()

class DomainListConfigScreen(ConfigScreen):
    '''Provides a base class for all config screens that require a domain list.'''

    def __init__(self, title):
        ConfigScreen.__init__(self, title)

    def get_domain_list_page(self, screen, defined=True, created=True):
        domuuids = self.get_libvirt().list_domains(defined, created)
        self.__has_domains = bool(domuuids)
        result = None

        if self.__has_domains:
            self.__domain_list = Listbox(0)
            for uuid in domuuids:
                domain = self.get_libvirt().get_domain(uuid)

                # dom is a vmmDomain
                self.__domain_list.append(domain.get_name(), domain)
            result = [self.__domain_list]
        else:
            grid = Grid(1, 1)
            grid.setField(Label("There are no domains available."), 0, 0)
            result = [grid]

        return result

    def get_selected_domain(self):
        return self.__domain_list.current()

    def has_selectable_domains(self):
        return self.__has_domains

class NetworkListConfigScreen(ConfigScreen):
    '''Provides a base class for all config screens that require a network list.'''

    def __init__(self, title):
        ConfigScreen.__init__(self, title)

    def get_network_list_page(self, screen, defined=True, started=True):
        uuids = self.get_libvirt().list_networks(defined, started)
        result = None

        if len(uuids) > 0:
            self.__has_networks = True
            self.__network_list = Listbox(0)
            for uuid in uuids:
                network = self.get_libvirt().get_network(uuid)
                self.__network_list.append(uuid, network.get_name())
            result = self.__network_list
        else:
            self.__has_networks = False
            result = Label("There are no networks available.")
        grid = Grid(1, 1)
        grid.setField(result, 0, 0)
        return [Label("Network List"),
                grid]

    def get_selected_network(self):
        uuid = self.__network_list.current()
        return self.get_libvirt().get_network(uuid)

    def has_selectable_networks(self):
        return self.__has_networks

class StorageListConfigScreen(ConfigScreen):
    '''Provides a base class for any configuration screen that deals with storage pool lists.'''

    def __init__(self, title):
        ConfigScreen.__init__(self, title)

    def get_storage_pool_list_page(self, screen, defined=True, created=True):
        pools = self.get_libvirt().list_storage_pools(defined=defined, created=created)
        if len(pools) > 0:
            self.__has_pools = True
            self.__pools_list = Listbox(0)
            for pool in pools:
                self.__pools_list.append(pool, pool)
            result = self.__pools_list
        else:
            self.__has_pools = False
            result = Label("There are no storage pools available.")
        grid = Grid(1, 1)
        grid.setField(result, 0, 0)
        return [Label("Storage Pool List"),
                grid]

    def get_selected_pool(self):
        return self.__pools_list.current()

    def has_selectable_pools(self):
        return self.__has_pools

    def get_storage_volume_list_page(self, screen):
        '''Requires that self.__pools_list have a selected element.'''
        pool = self.get_libvirt().get_storage_pool(self.get_selected_pool())
        if len(pool.listVolumes()) > 0:
            self.__has_volumes = True
            self.__volumes_list = Listbox(0)
            for volname in pool.listVolumes():
                volume = pool.storageVolLookupByName(volname)
                self.__volumes_list.append("%s (%0.2f GB)" % (volume.name(), volume.info()[2] / 1024**3), volume.name())
            result = self.__volumes_list
        else:
            self.__has_volumes = False
            result = Label("There are no storage volumes available.")
        grid = Grid(1, 1)
        grid.setField(result, 0, 0)
        return [Label("Storage Volume List"),
                grid]

    def get_selected_volume(self):
        return self.__volumes_list.current()

    def has_selectable_volumes(self):
        return self.__has_volumes

class HostListConfigScreen(ConfigScreen):
    '''Provides a base class for working with lists of libvirt hosts.'''

    def __init__(self, title):
        ConfigScreen.__init__(self, title)

    def get_connection_list_page(self, screen):
        connections = self.get_virt_manager_config().get_connection_list()
        result = None

        if len(connections) > 0:
            self.__has_connections = True
            self.__connection_list = Listbox(0)
            for connection in connections:
                self.__connection_list.append(connection, connection)
            result = self.__connection_list
        else:
            self.__has_connections = False
            result = Label("There are no defined connections.")
        grid = Grid(1, 1)
        grid.setField(result, 0, 0)
        return [Label("Host List"),
                grid]

    def get_selected_connection(self):
        return self.__connection_list.current()

    def has_selectable_connections(self):
        return self.__has_connections
