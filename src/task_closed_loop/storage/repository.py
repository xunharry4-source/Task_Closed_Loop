from collections import defaultdict
class InMemoryRepository:
    def __init__(self): self._data=defaultdict(dict)
    def add(self, collection, key, value): self._data[collection][key]=value
    def get(self, collection, key): return self._data[collection].get(key)
    def list(self, collection): return list(self._data[collection].values())
