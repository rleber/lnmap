import os
import tempfile
import unittest
from pathlib import Path

from lnmap import LinkMapper


class TestLinkMapper(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_indexes_traversal(self):
        sub_dir = self.root / "sub"
        sub_dir.mkdir()

        idx_root = self.root / ".lnmap_index.db"
        idx_root.touch()

        found = LinkMapper.indexes(sub_dir)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].path, idx_root)

    def test_hard_link_indexing(self):
        file1 = self.root / "file1.txt"
        file1.write_text("hello")

        file2 = self.root / "file2.txt"
        try:
            os.link(file1, file2)
        except OSError:
            self.skipTest("Hard links not supported on this filesystem/OS")

        db_path = LinkMapper.index_for(self.root)
        LinkMapper.index(db_path.parent)

        mapper = LinkMapper(self.root)
        links = mapper.find_links(include="hard")

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].link_type, "hard")
        self.assertEqual(len(links[0].paths), 2)

    def test_symlink_indexing(self):
        target = self.root / "target.txt"
        target.write_text("target file")

        sym = self.root / "sym.txt"
        try:
            sym.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks not supported on this OS")

        db_path = LinkMapper.index_for(self.root)
        LinkMapper.index(db_path.parent)

        mapper = LinkMapper(self.root)
        links = mapper.find_links(include="sym")

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].link_type, "sym")
        self.assertEqual(links[0].paths[0], sym.resolve())


if __name__ == "__main__":
    unittest.main()
