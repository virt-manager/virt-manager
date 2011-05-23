# setup.py - Copyright (C) 2009 Red Hat, Inc.
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

from setuptools import setup, find_packages

setup(name = "nodeadmin",
      version = "1.9.3",
      package_dir = {'nodeadmin': 'nodeadmin'},
      packages = find_packages('.'),
      entry_points = {
        'console_scripts': [
            'nodeadmin   = nodeadmin.nodeadmin:NodeAdmin',
            'addvm       = nodeadmin.adddomain:AddDomain',
            'startvm     = nodeadmin.startdomain:StartDomain',
            'stopvm      = nodeadmin.stopdomain:StopDomain',
            'pausevm     = nodeadmin.pausdomain:PauseDomain',
            'rmvm        = nodeadmin.removedomain:RemoveDomain',
            'migratevm   = nodeadmin.migratedomain:MigradeDomain',
            'createuser  = nodeadmin.createuser:CreateUser',
            'listvms     = nodeadmin.listdomains:ListDomains',
            'definenet   = nodeadmin.definenet:DefineNetwork',
            'createnet   = nodeadmin.createnetwork:CreateNetwork',
            'destroynet  = nodeadmin.destroynetwork:DestroyNetwork',
            'undefinenet = nodeadmin.undefinenetwork:UndefineNetwork',
            'listnets    = nodeadmin.listnetworks:ListNetworks',
            'addpool     = nodeadmin.addpool:AddStoragePool',
            'rmpool      = nodeadmin.removepool:RemoveStoragePool',
            'startpool   = nodeadmin.startpool:StartStoragePool',
            'stoppool    = nodeadmin.stoppool:StopStoragePool',
            'addvolume   = nodeadmin.addvolume:AddStorageVolume',
            'rmvolume    = nodeadmin.removevolume:RemoveStorageVolume',
            'listpools   = nodeadmin.listpools:ListPools']
        })
