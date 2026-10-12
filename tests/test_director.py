"""The automatic director: camera follows the bowling end, board after a wicket, hands off breaks."""
import pytest

from director import Director

SCENES = ["Camera Left", "Camera Right", "Full Board", "Break"]


class FakeOBS:
    connected = True
    error = ""

    def __init__(self, program="Camera Left"):
        self.program = program
        self.cuts = []

    def request(self, rtype, data=None, timeout=3.0):
        if rtype == "SetCurrentProgramScene":
            self.program = data["sceneName"]
            self.cuts.append(self.program)
            return {}
        if rtype == "GetCurrentProgramScene":
            return {"sceneName": self.program, "currentProgramSceneName": self.program}
        if rtype == "GetSceneList":
            return {"scenes": [{"sceneName": n} for n in SCENES]}
        raise AssertionError(rtype)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path):
    obs, clock = FakeOBS(), Clock()
    d = Director(obs=obs, board_seconds=10, state_file=str(tmp_path / "m.json"), clock=clock, log=lambda m: None)
    d.on_obs_connect()
    return d, obs, clock


def operator(d, obs, scene):
    """The operator picks a scene in OBS by hand."""
    obs.program = scene
    d.on_obs_event("CurrentProgramSceneChanged", {"sceneName": scene})


def test_bowling_end_alternates_each_over(rig):
    d, obs, _ = rig
    d.set_bowling("right")                       # first over from the right
    assert obs.program == "Camera Right"
    d.on_value("overs", "", "1")
    assert obs.program == "Camera Left"
    d.on_value("overs", "1", "2")
    assert obs.program == "Camera Right"
    d.on_value("overs", "2", "1")               # an overs correction goes back too
    assert obs.program == "Camera Left"


def test_bowling_button_part_way_through_innings(rig):
    d, obs, _ = rig
    d.on_value("overs", "", "7")
    d.set_bowling("left")                        # left is bowling over 8
    assert obs.program == "Camera Left" and d.start_end == "right"
    d.on_value("overs", "7", "8")
    assert obs.program == "Camera Right"


def test_wicket_shows_board_then_returns_to_same_camera(rig):
    d, obs, clock = rig
    d.set_bowling("left")
    d.on_value("wickets", "", "1")
    assert obs.program == "Full Board"
    clock.t += 9.9
    d.tick()
    assert obs.program == "Full Board"
    clock.t += 0.2
    d.tick()
    assert obs.program == "Camera Left"


def test_wicket_on_last_ball_returns_to_new_end(rig):
    d, obs, clock = rig
    d.set_bowling("left")
    d.on_value("wickets", "", "1")
    d.on_value("overs", "", "1")                 # over completes while the board is up
    assert obs.program == "Full Board"
    clock.t += 11
    d.tick()
    assert obs.program == "Camera Right"


def test_wicket_correction_down_is_ignored(rig):
    d, obs, _ = rig
    d.set_bowling("left")
    d.on_value("wickets", "", "3")
    d.on_obs_event("CurrentProgramSceneChanged", {"sceneName": "Full Board"})
    operator(d, obs, "Camera Left")
    obs.cuts.clear()
    d.on_value("wickets", "3", "2")
    assert obs.cuts == []


def test_break_scene_is_left_alone(rig):
    d, obs, clock = rig
    d.set_bowling("left")
    operator(d, obs, "Break")
    obs.cuts.clear()
    d.on_value("overs", "", "1")
    d.on_value("wickets", "", "1")
    clock.t += 30
    d.tick()
    assert obs.cuts == [] and obs.program == "Break"
    d.go_live()                                  # "Back to play" goes to the right end
    assert obs.program == "Camera Right"


def test_scene_button_then_back_to_play(rig):
    d, obs, clock = rig
    d.set_bowling("left")
    d.cut_to("Break")
    d.on_value("overs", "", "1")
    assert obs.program == "Break"
    d.go_live()
    assert obs.program == "Camera Right"


def test_operator_takes_over_from_board(rig):
    d, obs, clock = rig
    d.set_bowling("left")
    d.on_value("wickets", "", "1")
    operator(d, obs, "Break")                    # e.g. drinks called straight after the wicket
    clock.t += 30
    d.tick()
    assert obs.program == "Break"


def test_auto_off(rig):
    d, obs, _ = rig
    d.set_bowling("left")
    d.set_auto(False)
    obs.cuts.clear()
    d.on_value("overs", "", "1")
    d.on_value("wickets", "", "1")
    assert obs.cuts == []
    d.set_auto("toggle")
    assert d.auto


def test_manual_camera_choice_kept_until_next_over(rig):
    d, obs, _ = rig
    d.set_bowling("left")
    operator(d, obs, "Camera Right")            # a look from the other end
    obs.cuts.clear()
    d.on_value("total", "", "4")
    assert obs.cuts == []
    d.on_value("overs", "", "1")                 # right end bowls over 2: already there
    assert obs.cuts == []
    d.on_value("overs", "1", "2")
    assert obs.program == "Camera Left"


def test_end_of_innings(rig):
    d, obs, clock = rig
    d.set_batting_first("home")
    d.set_bowling("left")
    d.on_value("overs", "", "39")
    assert obs.program == "Camera Right"
    # the controller's end-of-innings refresh: wickets and overs blanked, then 1st inns set
    d.on_value("wickets", "7", "")
    d.on_value("overs", "39", "")
    assert obs.program == "Camera Right"
    d.on_value("first_inns", "", "212")
    assert obs.program == "Full Board"
    assert d.batting() == "away" and d.start_end == ""
    clock.t += 600
    d.tick()
    assert obs.program == "Full Board"          # held through the break
    d.set_bowling("right")
    assert obs.program == "Camera Right"
    d.on_value("overs", "", "1")
    assert obs.program == "Camera Left"


def test_swap_ends(rig):
    d, obs, _ = rig
    d.set_bowling("left")
    d.swap_ends()
    assert obs.program == "Camera Right" and d.start_end == "right"


def test_settings_saved(rig, tmp_path):
    d, _, _ = rig
    d.set_batting_first("away")
    d.set_bowling("right")
    d2 = Director(state_file=str(tmp_path / "m.json"), log=lambda m: None)
    assert d2.batting_first == "away" and d2.start_end == "right"


def test_missing_scene_reported(tmp_path):
    obs = FakeOBS()
    d = Director(obs=obs, scene_board="Scoreboard", log=lambda m: None)
    d.on_obs_connect()
    assert d.missing_scenes == ["Scoreboard"]


def test_without_obs_nothing_breaks():
    d = Director(log=lambda m: None)
    d.set_bowling("left")
    d.on_value("overs", "", "1")
    d.on_value("wickets", "", "1")
    assert d.bowling_end() == "right"
    assert d.status()["obs"]["connected"] is False


def test_dismissal_capture_drives_obs(monkeypatch):
    """Replay the real dismissal capture through the receiver with a fake OBS attached."""
    import ecs_receiver
    import ecs_protocol as proto
    from conftest import load_sr
    obs = FakeOBS()
    d = ecs_receiver.DIRECTOR
    monkeypatch.setattr(d, "obs", obs)
    monkeypatch.setattr(d, "log", lambda m: None)
    d.set_bowling("left")
    raw, fs = load_sr("set - runs - wicket - runs.sr")
    for field, value, copies in proto.decode_levels(raw & 1, fs):
        ecs_receiver.BOARD.apply(field, value, copies)
    assert "Full Board" in obs.cuts
