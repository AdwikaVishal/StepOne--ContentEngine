import importlib.metadata
_orig_v = importlib.metadata.version
def _version(name):
    if name == 'torchvision': return '0.20.0'
    return _orig_v(name)
importlib.metadata.version = _version
class DummyDist2:
    version = '0.20.0'
    metadata = {}
    def read_text(self, name):
        if name == 'METADATA': return 'Name: torchvision\nVersion: 0.20.0\n'
        return None
_orig_d = importlib.metadata.distribution
def _dist(name):
    if name == 'torchvision': return DummyDist2()
    return _orig_d(name)
importlib.metadata.distribution = _dist
