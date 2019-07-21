# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


from .blkiotune import DomainBlkiotune
from .clock import DomainClock
from .cpu import DomainCpu
from .cputune import DomainCputune
from .features import DomainFeatures
from .idmap import DomainIdmap
from .metadata import DomainMetadata
from .memorybacking import DomainMemoryBacking
from .memtune import DomainMemtune
from .numatune import DomainNumatune
from .os import DomainOs
from .pm import DomainPm
from .resource import DomainResource
from .seclabel import DomainSeclabel
from .keywrap import DomainKeyWrap
from .sysinfo import DomainSysinfo
from .vcpus import DomainVCPUs
from .xmlnsqemu import DomainXMLNSQemu
from .launch_security import DomainLaunchSecurity

__all__ = [l for l in locals() if l.startswith("Domain")]
