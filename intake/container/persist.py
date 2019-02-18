#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2018, Anaconda, Inc. and Intake contributors
# All rights reserved.
#
# The full license is in the LICENSE file, distributed with this software.
#-----------------------------------------------------------------------------

import os
import posixpath
import shutil
import time
import yaml
from ..catalog.local import YAMLFileCatalog, CatalogEntry
from .. import DataSource
from ..config import conf, logger
from ..source import import_name
from ..utils import make_path_posix


class PersistStore(YAMLFileCatalog):
    """
    Specialised catalog for persisted data-sources
    """
    _singleton = [None]

    def __new__(cls, *args, **kwargs):
        if cls._singleton[0] is None:
            o = object.__new__(cls)
            o._captured_init_args = args
            o._captured_init_kwargs = kwargs
            cls._singleton[0] = o
        return cls._singleton[0]

    def __init__(self, path=None):
        self.pdir = make_path_posix(path or conf.get('persist_path'))
        path = posixpath.join(self.pdir, 'cat.yaml')
        super(PersistStore, self).__init__(path)

    def _load(self):
        # make sure there's always something to load from
        try:
            os.makedirs(self.pdir)
        except (OSError, IOError):
            pass
        if not os.path.exists(self.path):
            with open(self.path, 'w') as f:
                f.write('sources: {}')
        super(PersistStore, self)._load()

    def getdir(self, source):
        """Clear/create a directory to store a persisted dataset into"""
        subdir = posixpath.join(self.pdir, source._tok)
        try:
            shutil.rmtree(subdir, ignore_errors=True)
            os.makedirs(subdir)
        except (IOError, OSError):
            pass
        return subdir

    def add(self, key, source):
        """Add the persisted source to the store under the given key

        key : str
            The unique token of the un-persisted, original source
        source : DataSource instance
            The thing to add to the persisted catalogue, referring to persisted
            data
        """
        with open(self.path) as f:
            data = yaml.load(f)
        data['sources'][key] = source._yaml()['sources'][source.name]
        with open(self.path, 'w') as fo:
            fo.write(yaml.dump(data, default_flow_style=False))
        self._entries[key] = source

    def get_tok(self, source):
        """Get string token from object

        Strings are assumed to already be a token; if source or entry, see
        if it is a persisted thing ("original_tok" is in its metadata), else
        generate its own token.
        """
        if isinstance(source, str):
            return source

        if isinstance(source, CatalogEntry):
            return source._metadata.get('original_tok', source._tok)

        if isinstance(source, DataSource):
            return source.metadata.get('original_tok', source._tok)
        raise IndexError

    def remove(self, source, delfiles=True):
        """Remove a dataset from the persist store

        source : str or DataSource or Lo
            If a str, this is the unique ID of the original source, which is
            the key of the persisted dataset within the store. If a source,
            can be either the original or the persisted source.
        delfiles : bool
            Whether to remove the on-disc artifact
        """
        source = self.get_tok(source)
        data = yaml.load(open(self.path))
        del data['sources'][source]
        with open(self.path, 'w') as fo:
            fo.write(yaml.dump(data, default_flow_style=False))
        if delfiles:
            path = posixpath.join(self.pdir, source)
            try:
                shutil.rmtree(path)
            except IOError as e:
                logger.debug("Failed to delete persisted data dir %s" % path)
        self._entries.pop(source)

    def clear(self):
        """Remove all persisted sources, files and catalog"""
        shutil.rmtree(self.pdir)

    def backtrack(self, source):
        """Given a unique key in the store, recreate original source"""
        key = self.get_tok(source)
        s = self[key]()
        cls, args, kwargs = s.metadata['original_source']
        cls = import_name(cls)
        sout = cls(*args, **kwargs)
        sout.metadata = s.metadata['original_metadata']
        sout.name = s.metadata['original_name']
        return sout

    def refresh(self, key):
        """Recreate and re-persist the source for the given unique ID"""
        s0 = self[key]
        s = self.backtrack(key)
        s.persist(**s0.metadata['persist_kwargs'])

    def needs_refresh(self, source):
        """Has the (persisted) source expired in the store

        Will return True if the source is not in the store at all, if it's
        TTL is set to None, or if more seconds have passed than the TTL.
        """
        now = time.time()
        if source._tok in self:
            s0 = self[source._tok]
            if self[source._tok].metadata.get('ttl', None):
                then = s0.metadata['timestamp']
                if s0.metadata['ttl'] < then - now:
                    return True
            return False
        return True


store = PersistStore()
