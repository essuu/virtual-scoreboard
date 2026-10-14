"""Put the scoreboard into the OBS scenes the director switches between.

    Camera Left / Camera Right   score bar on top of the camera picture
    Full Board                   the full scoreboard (classicboard layout)
    Starting Soon / Break /      a holding picture (/break?kind=...) in the scoreboard's colours, for
    Technical Difficulties       the Stream Deck's Breaks keys. Only put into a scene that is empty,
                                 so your own picture in one of these scenes is left alone.

The score bar lives in one browser source ("Score Bar") inside its own scene ("Score Overlay"),
which is added to both camera scenes. One browser instance means one connection to the receiver,
and changing its URL or size in OBS changes both cameras.

Only adds what is missing; it never removes or edits anything you made. A scene that already shows
a page from this receiver (directly, or inside a nested scene such as your own overlay scene) is
left as it is, so running it again, or after setting OBS up by hand, adds nothing twice.
"""
from urllib.parse import urlsplit, parse_qs

OVERLAY_SCENE = "Score Overlay"
BAR_INPUT = "Score Bar"
BOARD_INPUT = "Full Scoreboard"
# break scenes the Stream Deck's Breaks keys cut to: scene -> (card kind, browser source name)
BREAK_SCENES = {"Starting Soon": ("soon", "Starting Soon Card"),
                "Break": ("break", "Break Card"),
                "Technical Difficulties": ("technical", "Technical Difficulties Card")}
TEST_INPUTS = {"left": "Test Camera Left", "right": "Test Camera Right"}
SCENE_TYPE = "OBS_SOURCE_TYPE_SCENE"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


class Setup:
    def __init__(self, obs, port):
        self.obs, self.port = obs, int(port)
        self._urls = {}

    def req(self, rtype, data=None):
        return self.obs.request(rtype, data)

    # ------------------------------------------------------------------ inspecting
    def url_of(self, input_name):
        if input_name not in self._urls:
            try:
                self._urls[input_name] = self.req("GetInputSettings", {"inputName": input_name}) \
                    .get("inputSettings", {}).get("url", "")
            except Exception:
                self._urls[input_name] = ""
        return self._urls[input_name]

    def ours(self, url, board=None):
        """Is this URL one of our pages? board=True: a board layout; False: the bar; None: either."""
        try:
            u = urlsplit(url)
            if u.port != self.port or (u.hostname or "") not in LOCAL_HOSTS:
                return False
        except ValueError:
            return False
        if u.path not in ("", "/", "/scoreboard", "/index.html"):
            return False
        layout = parse_qs(u.query).get("layout", ["bar"])[-1]
        if board is None:
            return True
        return (layout != "bar") == board

    def items(self, scene):
        try:
            return self.req("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        except Exception:
            return []           # e.g. a group

    def find(self, scene, board=None, depth=0):
        """The top-level item in 'scene' that shows one of our pages (itself, or via a nested
        scene), or None."""
        for it in self.items(scene):
            name = it.get("sourceName", "")
            if it.get("inputKind") == "browser_source" and self.ours(self.url_of(name), board):
                return it
            if it.get("sourceType") == SCENE_TYPE and depth < 2 and self.find(name, board, depth + 1):
                return it
        return None

    # ------------------------------------------------------------------ adding
    def add_browser(self, scene, input_name, url, size, existing):
        if input_name in existing:          # the source exists already: reuse it
            self.req("CreateSceneItem", {"sceneName": scene, "sourceName": input_name})
        else:
            w, h = size
            self.req("CreateInput", {
                "sceneName": scene, "inputName": input_name, "inputKind": "browser_source",
                "inputSettings": {"url": url, "width": w, "height": h, "shutdown": False,
                                  "restart_when_active": False},
                "sceneItemEnabled": True})
            existing.add(input_name)
        self._urls[input_name] = url

    def to_top(self, scene, item):
        n = len(self.items(scene))
        if item.get("sceneItemIndex", n - 1) != n - 1:
            self.req("SetSceneItemIndex", {"sceneName": scene, "sceneItemId": item["sceneItemId"],
                                           "sceneItemIndex": n - 1})
            return True
        return False

    def run(self, cameras, board_scene, bar_url, board_url, break_url=None):
        """Returns a list of what changed (empty if OBS was already set up).
        break_url(kind) -> URL of that break card; None leaves the break scenes out."""
        done = []
        vs = self.req("GetVideoSettings")
        size = (int(vs.get("baseWidth") or 1920), int(vs.get("baseHeight") or 1080))
        scenes = {s.get("sceneName") for s in self.req("GetSceneList").get("scenes", [])}
        existing = {i.get("inputName") for i in
                    self.req("GetInputList", {"inputKind": "browser_source"}).get("inputs", [])}

        for scene in list(cameras) + [board_scene]:
            if scene not in scenes:
                self.req("CreateScene", {"sceneName": scene})
                scenes.add(scene)
                done.append('created scene "%s"%s' % (scene, " - add the camera to it" if scene in cameras else ""))

        # cameras: the shared overlay scene, kept on top of the camera picture
        need = [c for c in cameras if not self.find(c)]
        if need:
            if OVERLAY_SCENE not in scenes:
                self.req("CreateScene", {"sceneName": OVERLAY_SCENE})
                scenes.add(OVERLAY_SCENE)
                done.append('created scene "%s"' % OVERLAY_SCENE)
            if not self.find(OVERLAY_SCENE, board=False):
                self.add_browser(OVERLAY_SCENE, BAR_INPUT, bar_url, size, existing)
                done.append('added the score bar to "%s"' % OVERLAY_SCENE)
            for c in need:
                self.req("CreateSceneItem", {"sceneName": c, "sourceName": OVERLAY_SCENE})
                done.append('added the score bar to "%s"' % c)
        for c in cameras:
            it = self.find(c)
            if it and self.to_top(c, it):
                done.append('moved the score bar to the top of "%s"' % c)

        # full board
        if not self.find(board_scene, board=True):
            self.add_browser(board_scene, BOARD_INPUT, board_url, size, existing)
            done.append('added the full scoreboard to "%s"' % board_scene)

        # break scenes: create any that are missing; put our card only into an empty one
        if break_url:
            for scene, (kind, input_name) in BREAK_SCENES.items():
                if scene not in scenes:
                    self.req("CreateScene", {"sceneName": scene})
                    scenes.add(scene)
                    done.append('created scene "%s"' % scene)
                if not self.items(scene):
                    self.add_browser(scene, input_name, break_url(kind), size, existing)
                    done.append('added the %s card to "%s"' % (scene.lower(), scene))
        return done

    def keep_on_top(self, scene):
        """After something new is added to a camera scene, put the score bar back above it."""
        it = self.find(scene)
        return bool(it) and self.to_top(scene, it)

    # ------------------------------------------------------------------ test cameras
    def is_test_card(self, input_name):
        try:
            u = urlsplit(self.url_of(input_name))
            return u.port == self.port and u.path == "/testcard"
        except ValueError:
            return False

    def add_test_cards(self, cameras, url_for):
        """Put a test card (a browser source standing in for the camera) at the bottom of each
        camera scene. cameras: {"left": scene, "right": scene}; url_for(end) -> page URL."""
        done = []
        vs = self.req("GetVideoSettings")
        w, h = int(vs.get("baseWidth") or 1920), int(vs.get("baseHeight") or 1080)
        existing = {i.get("inputName") for i in
                    self.req("GetInputList", {"inputKind": "browser_source"}).get("inputs", [])}
        scenes = {s.get("sceneName") for s in self.req("GetSceneList").get("scenes", [])}
        for end, scene in cameras.items():
            name = TEST_INPUTS[end]
            if scene not in scenes:
                self.req("CreateScene", {"sceneName": scene})
                done.append('created scene "%s"' % scene)
            if any(it.get("sourceName") == name for it in self.items(scene)):
                continue
            if name in existing:
                r = self.req("CreateSceneItem", {"sceneName": scene, "sourceName": name})
            else:
                r = self.req("CreateInput", {
                    "sceneName": scene, "inputName": name, "inputKind": "browser_source",
                    "inputSettings": {"url": url_for(end), "width": w, "height": h,
                                      "shutdown": False, "restart_when_active": False},
                    "sceneItemEnabled": True})
                existing.add(name)
            self.req("SetSceneItemIndex", {"sceneName": scene, "sceneItemId": r["sceneItemId"],
                                           "sceneItemIndex": 0})
            done.append('added "%s" to "%s"' % (name, scene))
        return done

    def remove_test_cards(self):
        """Remove the test cards added above (only those, from every scene)."""
        done = []
        existing = {i.get("inputName") for i in
                    self.req("GetInputList", {"inputKind": "browser_source"}).get("inputs", [])}
        for name in TEST_INPUTS.values():
            if name in existing and self.is_test_card(name):
                self.req("RemoveInput", {"inputName": name})
                done.append('removed "%s"' % name)
        return done
