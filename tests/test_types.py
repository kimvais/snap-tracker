import unittest
import uuid

from snap_tracker.types import Game


class TypesTest(unittest.TestCase):
    def test_game(self):
        random_id = uuid.uuid4()
        new_game = Game(random_id)
        with self.subTest('test equality'):
            assert new_game == Game.new(str(random_id))
            assert new_game == random_id
            assert new_game == str(random_id)
        with self.subTest('test inequality'):
            waiting_game = Game()
            assert waiting_game != new_game
            assert waiting_game != random_id


if __name__ == '__main__':
    unittest.main()
