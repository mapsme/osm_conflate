try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree
from .data import SourcePoint
from .conflate import run
from .version import __version__
from .profile import Profile, ProfileException
from .conflator import OsmConflator
