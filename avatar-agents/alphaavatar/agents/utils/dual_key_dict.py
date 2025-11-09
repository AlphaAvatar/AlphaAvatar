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
from collections import UserDict


class AttrDict(UserDict):
    """A dictionary supporting both attribute-style and key-style access."""

    def __init__(self, mapping=None, **kwargs):
        super().__init__()
        # normalize & wrap after data exists
        if mapping:
            for k, v in dict(mapping).items():
                self.data[k] = self._wrap(v)
        for k, v in kwargs.items():
            self.data[k] = self._wrap(v)

    def __getattr__(self, name):
        # attribute lookup falls back to dict items
        try:
            data = object.__getattribute__(self, "data")
            return data[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        # keep internals as real attributes
        if name == "data" or name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        # if data not ready yet, store as real attribute (during __init__)
        if "data" not in self.__dict__:
            object.__setattr__(self, name, value)
            return
        # normal path: write into mapping with wrapping
        self.data[name] = self._wrap(value)

    def __delattr__(self, name):
        if name == "data" or name.startswith("_"):
            # allow deleting real attributes if really needed
            try:
                del self.__dict__[name]
            except KeyError as e:
                raise AttributeError(name) from e
            return
        try:
            del self.data[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(value))

    @classmethod
    def _wrap(cls, v):
        if isinstance(v, dict):
            return cls(v)
        if isinstance(v, list):
            return [cls._wrap(i) for i in v]
        return v


class DualKeyDict(AttrDict):
    """
    A dictionary that can be accessed both by key and by the 'id' field of its values.
    """

    def __init__(self, mapping=None, *, id_field="id", **kwargs):
        # store internals as true attributes (not in data)
        self._id_field = id_field
        self._id_index = {}  # Mapping: id_value -> object
        super().__init__(mapping or {}, **kwargs)
        # Build initial index
        for v in self.data.values():
            self._index_add(v)

    # --- Helper methods ---
    def _get_id_value(self, v):
        """Extract the id value from either a dict or an object."""
        if isinstance(v, dict | AttrDict):
            return v.get(self._id_field, None)
        return getattr(v, self._id_field, None)

    def _index_add(self, v):
        idv = self._get_id_value(v)
        if idv is not None:
            self._id_index[idv] = v

    def _index_remove(self, v):
        idv = self._get_id_value(v)
        if idv is not None and self._id_index.get(idv) is v:
            self._id_index.pop(idv, None)

    # --- Core overrides ---
    def __setitem__(self, key, value):
        if key in self.data:
            self._index_remove(self.data[key])
        wrapped = self._wrap(value)
        super().__setitem__(key, wrapped)
        self._index_add(wrapped)

    def __delitem__(self, key_or_id):
        # Delete by key
        if key_or_id in self.data:
            self._index_remove(self.data[key_or_id])
            return super().__delitem__(key_or_id)
        # Delete by id
        obj = self._id_index.pop(key_or_id, None)
        if obj is None:
            raise KeyError(key_or_id)
        for k, v in list(self.data.items()):
            if v is obj:
                super().__delitem__(k)
                return
        raise KeyError(key_or_id)

    def __getitem__(self, key_or_id):
        try:
            return super().__getitem__(key_or_id)
        except KeyError:
            obj = self._id_index.get(key_or_id)
            if obj is not None:
                return obj
            raise

    # --- Explicit API methods ---
    def get_by_id(self, id_value, default=None):
        return self._id_index.get(id_value, default)

    def pop_by_id(self, id_value, default=None):
        try:
            self.__delitem__(id_value)
            return True
        except KeyError:
            if default is not None:
                return default
            raise

    def rebuild_index(self):
        self._id_index.clear()
        for v in self.data.values():
            self._index_add(v)
