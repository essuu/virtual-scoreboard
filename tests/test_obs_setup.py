"""Adding the score bar to the camera scenes and the scoreboard to the Full Board scene."""
from director import Director
from fake_obs import ModelOBS
from obs_setup import BAR_INPUT, BOARD_INPUT, OVERLAY_SCENE

BAR = "http://127.0.0.1:8765/"


def director(obs):
    d = Director(obs=obs, log=lambda m: None)
    d.port = 8765
    return d


def bar_on_top(obs, scene):
    """The score bar is the top item of the scene (directly or via the overlay scene)."""
    top = obs.scenes[scene][-1]["sourceName"]
    return top == OVERLAY_SCENE and obs.names(OVERLAY_SCENE) == [BAR_INPUT]


def test_fresh_obs_with_camera_scenes():
    obs = ModelOBS(["Camera Left", "Camera Right"], canvas=(1280, 720))
    obs.add_source("Camera Left", "IP cam left")
    obs.add_source("Camera Right", "IP cam right")
    d = director(obs)
    d.on_obs_connect()
    assert bar_on_top(obs, "Camera Left") and bar_on_top(obs, "Camera Right")
    assert obs.names("Camera Left") == ["IP cam left", OVERLAY_SCENE]
    bar = obs.inputs[BAR_INPUT]["settings"]
    assert bar["url"] == BAR and (bar["width"], bar["height"]) == (1280, 720)
    assert bar["shutdown"] is False and bar["restart_when_active"] is False
    assert obs.names("Full Board") == [BOARD_INPUT]
    assert "layout=classicboard" in obs.inputs[BOARD_INPUT]["settings"]["url"]
    assert d.missing_scenes == []
    # running again changes nothing
    before = {k: list(v) for k, v in obs.scenes.items()}
    assert d.setup_obs() == []
    assert {k: list(v) for k, v in obs.scenes.items()} == before


def test_existing_overlay_is_not_doubled():
    """The user already put the scoreboard on one camera by hand (nested in their own scene)."""
    obs = ModelOBS(["Camera Left", "Camera Right", "Overlay - Score", "Full Board"])
    obs.add_source("Overlay - Score", "My scoreboard", "browser_source",
                   {"url": "http://localhost:8765/?title=Tenterden%20CC"})
    obs.add_source("Camera Left", "cam L")
    obs.add_item("Camera Left", "Overlay - Score")
    obs.add_source("Full Board", "Board page", "browser_source",
                   {"url": "http://127.0.0.1:8765/?layout=classicboard"})
    obs.add_source("Camera Right", "cam R")
    d = director(obs)
    d.setup_obs()
    assert obs.names("Camera Left") == ["cam L", "Overlay - Score"]          # untouched
    assert obs.names("Camera Right") == ["cam R", OVERLAY_SCENE]             # added
    assert obs.names("Full Board") == ["Board page"]                         # untouched


def test_other_port_or_bar_on_board_scene_does_not_count():
    obs = ModelOBS(["Camera Left", "Camera Right", "Full Board"])
    obs.add_source("Camera Left", "old", "browser_source", {"url": "http://127.0.0.1:8080/"})
    obs.add_item("Full Board", "old")                                       # wrong port
    d = director(obs)
    d.setup_obs()
    assert obs.names("Camera Left")[-1] == OVERLAY_SCENE
    assert obs.names("Full Board") == ["old", BOARD_INPUT]


def test_missing_scenes_created():
    obs = ModelOBS(["Scene"])
    d = director(obs)
    done = d.setup_obs()
    for s in ("Camera Left", "Camera Right", "Full Board"):
        assert s in obs.scenes
    assert any("add the camera" in x for x in done)


def test_camera_added_later_goes_under_the_bar():
    obs = ModelOBS(["Camera Left", "Camera Right"])
    d = director(obs)
    d.on_obs_connect()
    obs.add_source("Camera Right", "new IP cam")                             # lands on top in OBS
    d.on_obs_event("SceneItemCreated", {"sceneName": "Camera Right", "sourceName": "new IP cam"})
    assert obs.names("Camera Right") == ["new IP cam", OVERLAY_SCENE]


def test_bar_moved_to_top_on_connect():
    obs = ModelOBS(["Camera Left", "Camera Right", "Full Board"])
    d = director(obs)
    d.setup_obs()
    obs.add_source("Camera Left", "cam added while receiver was off")
    d.on_obs_connect()
    assert obs.names("Camera Left")[-1] == OVERLAY_SCENE


def test_bar_options_and_port():
    obs = ModelOBS(["Camera Left", "Camera Right", "Full Board"])
    d = director(obs)
    d.port = 8090
    d.bar_query = "title=Tenterden%20CC&home=Tenterden"
    d.setup_obs()
    assert obs.inputs[BAR_INPUT]["settings"]["url"] == "http://127.0.0.1:8090/?title=Tenterden%20CC&home=Tenterden"


def test_auto_setup_off():
    obs = ModelOBS(["Camera Left", "Camera Right", "Full Board"])
    d = director(obs)
    d.auto_setup = False
    d.on_obs_connect()
    assert obs.names("Camera Left") == [] and BAR_INPUT not in obs.inputs


def test_test_cameras_added_under_the_bar_and_removed():
    obs = ModelOBS(["Camera Left", "Camera Right", "Full Board"])
    obs.add_source("Camera Right", "IP cam right")
    d = director(obs)
    d.on_obs_connect()
    d.test_cameras(True)
    assert obs.names("Camera Left") == ["Test Camera Left", OVERLAY_SCENE]
    assert obs.names("Camera Right") == ["Test Camera Right", "IP cam right", OVERLAY_SCENE]
    assert obs.inputs["Test Camera Left"]["settings"]["url"] == "http://127.0.0.1:8765/testcard?end=left"
    assert obs.inputs["Test Camera Right"]["settings"]["url"].endswith("end=right")
    assert d.test_cameras(True) == []                       # nothing doubled
    assert obs.names("Camera Left") == ["Test Camera Left", OVERLAY_SCENE]
    d.test_cameras(False)
    assert obs.names("Camera Left") == [OVERLAY_SCENE]
    assert obs.names("Camera Right") == ["IP cam right", OVERLAY_SCENE]
    assert "Test Camera Left" not in obs.inputs


def test_test_cameras_on_a_blank_obs():
    obs = ModelOBS(["Scene"])
    d = director(obs)
    d.test_cameras(True)
    assert obs.names("Camera Left") == ["Test Camera Left", OVERLAY_SCENE]
    assert obs.names("Full Board") == [BOARD_INPUT]


def test_remove_leaves_a_source_of_the_same_name_that_is_not_ours():
    obs = ModelOBS(["Camera Left"])
    obs.add_source("Camera Left", "Test Camera Left", "browser_source", {"url": "https://example.com/"})
    director(obs).test_cameras(False)
    assert obs.names("Camera Left") == ["Test Camera Left"]


# ---------------------------------------------------------------- break scenes
from obs_setup import BREAK_SCENES


def test_break_scenes_created_with_cards():
    obs = ModelOBS(["Camera Left", "Camera Right"])
    d = director(obs)
    d.bar_query = "title=Tenterden%20CC&home=Tenterden&scale=0.8"
    done = d.setup_obs()
    for scene, (kind, name) in BREAK_SCENES.items():
        assert obs.names(scene) == [name]
        url = obs.inputs[name]["settings"]["url"]
        assert url.startswith("http://127.0.0.1:8765/break?kind=%s" % kind)
        assert "title=Tenterden%20CC" in url and "home=Tenterden" in url and "scale" not in url
        assert any(scene in x for x in done)
    # the break pages are not mistaken for the score bar or board
    assert obs.names("Full Board") == [BOARD_INPUT]
    before = {k: list(v) for k, v in obs.scenes.items()}
    assert d.setup_obs() == []
    assert {k: list(v) for k, v in obs.scenes.items()} == before


def test_own_break_picture_left_alone():
    obs = ModelOBS(["Camera Left", "Camera Right", "Break", "Starting Soon"])
    obs.add_source("Break", "My tea picture", "image_source", {"file": "tea.png"})
    d = director(obs)
    d.setup_obs()
    assert obs.names("Break") == ["My tea picture"]                      # untouched
    assert obs.names("Starting Soon") == ["Starting Soon Card"]          # existed but empty: filled
    assert obs.names("Technical Difficulties") == ["Technical Difficulties Card"]


def test_break_scenes_can_be_turned_off():
    obs = ModelOBS(["Camera Left", "Camera Right"])
    d = director(obs)
    d.break_scenes = False
    d.setup_obs()
    assert not any(s in obs.scenes for s in BREAK_SCENES)
