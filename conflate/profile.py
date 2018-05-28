import json
from .data import SourcePoint  # So we don't have to import this in profiles
from . import etree


class ProfileException(Exception):
    """An exception class for the Profile instance."""
    def __init__(self, attr, desc):
        super().__init__('Field missing in profile: {} ({})'.format(attr, desc))


class Profile:
    """A wrapper for a profile.

    A profile is a python script that sets a few local variables.
    These variables become properties of the profile, accessible with
    a "get" method. If something is a function, it will be called,
    optional parameters might be passed to it.

    You can compile a list of all supported variables by grepping through
    this code, or by looking at a few example profiles. If something
    is required, you will be notified of that.
    """
    def __init__(self, fileobj, par=None):
        global param
        param = par
        if isinstance(fileobj, dict):
            self.profile = fileobj
        elif hasattr(fileobj, 'read'):
            s = fileobj.read().replace('\r', '')
            if s[0] == '{':
                self.profile = json.loads(s)
            else:
                self.profile = {}
                exec(s, globals(), self.profile)
        else:
            # Got a class
            self.profile = {name: getattr(fileobj, name)
                            for name in dir(fileobj) if not name.startswith('_')}
        self.max_distance = self.get('max_distance', 100)

    def has(self, attr):
        return attr in self.profile

    def get(self, attr, default=None, required=None, args=None):
        if attr in self.profile:
            value = self.profile[attr]
            if callable(value):
                if args is None:
                    return value()
                else:
                    return value(*args)
            else:
                return value
        if required is not None:
            raise ProfileException(attr, required)
        return default

    def get_raw(self, attr, default=None):
        if attr in self.profile:
            return self.profile[attr]
        return default
