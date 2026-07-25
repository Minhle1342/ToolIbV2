import os
import sys

# Thêm đường dẫn vào sys.path để có thể import từ app
sys.path.insert(0, r"d:\Thuctap\ToolIb-main\ToolIb-main")

from utils import scan_and_sync_images

class DummyProject:
    def __init__(self, root_path):
        self.root_path = root_path
        self.id = 999
        self.images = []

class DummyDB:
    class Session:
        def add(self, *args): pass
        def commit(self): pass
    session = Session()

import utils
if __name__ == "__main__":
    utils.db = DummyDB()
    p = DummyProject(r"D:\TestcoYaml")
    count = utils.scan_and_sync_images(p)
    print("Added count:", count)
