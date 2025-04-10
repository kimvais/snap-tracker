import pathlib
import unittest

from snap_tracker._game_log import (
    GameLogEvent,
    _parse_line,
    _parse_log_lines,
)
from snap_tracker.data_types import GameMode


class GameLogTest(unittest.TestCase):
    def test_matchmaking_results(self):
        line = r'OnMatchmakingMatchFound|GameId=60c106af-c97f-445b-8840-d6433be947f9|GameHostUrl=wss://eu-central-1-ws-cf.nvprod.snapgametech.com/v33.16-7-game'
        event = _parse_line(line)
        assert event.type == GameLogEvent.Type.GAME_START
        assert event.data['game_id']

    def test_game_result_ack(self):
        line = r'RemoteGame|SendRequestObject|RequestType=CubeGame.AckGameResultRequest'
        event = _parse_line(line)
        assert event.type == GameLogEvent.Type.GAME_END

    def test_game_turn_end(self):
        line = r'EndTurn|Turn=3'
        event = _parse_line(line)
        assert event.type == GameLogEvent.Type.TURN_END
        assert int(event.data['turn']) == 3

    def test_card_staging(self):
        line = r'StageCard|CardDefId=Deadpool|CardEntityId=62|ZoneEntityId=11|Turn=6'
        event = _parse_line(line)
        assert event.type == GameLogEvent.Type.CARD_PLAYED
        assert event.data['card_def_id'] == 'Deadpool'
        assert int(event.data['zone_eid']) == 11
        assert int(event.data['turn']) == 6

    def test_game_initializing(self):
        line = r'GameManager|Initialize|gameMode=Remote|leagueDefId=Ranked|sceneToLoadAfterGame=Play'
        event = _parse_line(line)
        assert event.type == GameLogEvent.Type.GAME_INITIALIZING
        assert GameMode(event.data['game_mode']) == GameMode.RANKED

    def test_sample_log(self):
        log = pathlib.Path(__file__).parent / 'test_data' / 'Player.log'
        with log.open() as f:
            events = list(_parse_log_lines(f.readlines()))
            assert events[0].type == GameLogEvent.Type.GAME_INITIALIZING
            assert events[1].type == GameLogEvent.Type.GAME_START
            assert events[-1].type == GameLogEvent.Type.GAME_END
            other_events = events[2:-1]
            turn_end_events = [ev for ev in other_events if ev.type == GameLogEvent.Type.TURN_END]
            assert [int(ev.data['turn']) for ev in turn_end_events] == list(range(1, 7))
