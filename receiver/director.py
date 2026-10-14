"""Automatic OBS director: picks the camera at the bowler's end and shows the full board after a wicket.

The two cameras sit on the sightscreens, so the camera to show is the one behind the bowler. Ends
swap every over, so once we know which end bowled the first over of the innings, the completed
overs count from the controller (field 7) tells us the end for every later over:

    bowling end = start end    when completed overs is even
                = the other    when it is odd

"start_end" is set from the Stream Deck (or the status page) with "Left/Right end bowling now".
That button can be pressed at any time - it also fixes a wrong guess part-way through an innings.

Rules
  * Overs change           -> cut to the camera at the new bowling end (only from a camera scene).
  * Wickets go up          -> full-board scene for board_seconds, then back to the bowling-end camera.
  * End of innings         -> full-board scene, held until the next "end bowling now" press.
  * Operator picks another scene (Break, Starting Soon...) -> the director leaves it alone; changes
    made while it is up are remembered, and "Back to play" cuts to the right camera.
"""
import json, os, queue, threading, time

import obs_setup

LEFT, RIGHT = "left", "right"
HOME, AWAY = "home", "away"


def other_end(end):
    return {LEFT: RIGHT, RIGHT: LEFT}.get(end, "")


def other_team(team):
    return {HOME: AWAY, AWAY: HOME}.get(team, "")


def num(v):
    v = (v or "").strip()
    return int(v) if v.isdigit() else 0


class Director:
    def __init__(self, obs=None, scene_left="Camera Left", scene_right="Camera Right",
                 scene_board="Full Board", board_seconds=10.0, state_file=None,
                 clock=time.monotonic, log=None):
        self.lock = threading.RLock()
        self.obs = obs
        self.scenes = {LEFT: scene_left, RIGHT: scene_right, "board": scene_board}
        self.board_seconds = float(board_seconds)
        self.state_file = state_file
        self.clock = clock
        self.log = log or (lambda m: print(time.strftime("%H:%M:%S"), " ", m, flush=True))
        self.on_change = None           # called after match settings change (scoreboard refresh)
        # saved settings
        self.batting_first = ""         # "home" / "away" / ""
        self.start_end = ""             # end that bowls when completed overs is even
        self.auto = True
        # live state
        self.overs = 0
        self.wickets = 0
        self.second_innings = False
        self.program = None             # current OBS programme scene (None = unknown)
        self.last_camera = None
        self.board_active = False       # the director put the board up and will take it down
        self.board_until = None         # clock() time to go back; None = hold
        self.missing_scenes = []
        # OBS scene set-up (score bar on the cameras, full board scene)
        self.auto_setup = True
        self.port = 8765
        self.bar_query = ""
        self.board_query = "layout=classicboard&bg=1"
        self.break_scenes = True        # create Starting Soon / Break / Technical Difficulties
        self.setup_done = []            # what the last set-up changed
        self.setup_error = ""
        self.history = []               # recent decisions for the status page
        self._queue = queue.Queue()
        self._started = False
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        if not self.state_file:
            return
        try:
            with open(self.state_file) as f:
                s = json.load(f)
            self.batting_first = s.get("batting_first", "") if s.get("batting_first") in (HOME, AWAY) else ""
            self.start_end = s.get("start_end", "") if s.get("start_end") in (LEFT, RIGHT) else ""
            self.auto = bool(s.get("auto", True))
        except Exception:
            pass

    def _save(self):
        if not self.state_file:
            return
        try:
            tmp = self.state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"batting_first": self.batting_first, "start_end": self.start_end,
                           "auto": self.auto}, f)
            os.replace(tmp, self.state_file)
        except Exception as e:
            self.log("director: could not save settings: %s" % e)

    def _changed(self):
        self._save()
        if self.on_change:
            try:
                self.on_change()
            except Exception as e:
                self.log("director: refresh failed: %s" % e)

    def _note(self, text):
        self.history.append({"t": time.time(), "text": text})
        self.history = self.history[-30:]
        self.log("Director: " + text)

    # ------------------------------------------------------------------ derived
    def bowling_end(self):
        """End bowling the current over, or '' if not set."""
        if not self.start_end:
            return ""
        return self.start_end if self.overs % 2 == 0 else other_end(self.start_end)

    def target_camera(self):
        end = self.bowling_end()
        return self.scenes[end] if end else None

    def batting(self):
        if not self.batting_first:
            return ""
        return other_team(self.batting_first) if self.second_innings else self.batting_first

    def is_camera(self, scene):
        return scene is not None and scene in (self.scenes[LEFT], self.scenes[RIGHT])

    def match_info(self):
        # read without the lock: called from inside the scoreboard's lock
        return {"batting_first": self.batting_first, "batting": self.batting(),
                "second_innings": self.second_innings}

    # ------------------------------------------------------------------ OBS
    def _obs_ok(self):
        return self.obs is not None and getattr(self.obs, "connected", False)

    def _cut(self, scene, why):
        if not scene:
            return False
        if not self._obs_ok():
            self._note("%s -> %s (not sent: OBS not connected)" % (why, scene))
            return False
        try:
            self.obs.request("SetCurrentProgramScene", {"sceneName": scene})
        except Exception as e:
            self._note("%s -> %s FAILED: %s" % (why, scene, e))
            return False
        self.program = scene
        if self.is_camera(scene):
            self.last_camera = scene
        self._note("%s -> %s" % (why, scene))
        return True

    def page_url(self, query):
        return "http://127.0.0.1:%d/%s" % (self.port, ("?" + query) if query else "")

    def break_url(self, kind):
        """The break card for one of the break scenes, with the score bar's options (title, team
        names) passed on so they match."""
        extra = "&".join(p for p in self.bar_query.split("&") if p.split("=")[0] in ("title", "home", "away"))
        return "http://127.0.0.1:%d/break?kind=%s%s" % (self.port, kind, ("&" + extra) if extra else "")

    def _run_setup(self, st):
        return st.run([self.scenes[LEFT], self.scenes[RIGHT]], self.scenes["board"],
                      self.page_url(self.bar_query), self.page_url(self.board_query),
                      self.break_url if self.break_scenes else None)

    def setup_obs(self):
        """Add the score bar to the camera scenes, the scoreboard to the board scene and the break
        scenes with their cards (only what's missing). Returns the list of changes."""
        if not self._obs_ok():
            self.setup_error = "OBS not connected"
            return []
        try:
            done = self._run_setup(obs_setup.Setup(self.obs, self.port))
            self.setup_error = ""
        except Exception as e:
            self.setup_error = str(e)
            self.log("Director: OBS set-up failed: %s" % e)
            return []
        self.setup_done = done
        for d in done:
            self._note("OBS set-up: " + d)
        self.refresh_scenes()
        return done

    def test_cameras(self, on=True):
        """Add (or remove) stand-in test cards in the camera scenes, for trying things out at home."""
        if not self._obs_ok():
            self.setup_error = "OBS not connected"
            return []
        try:
            st = obs_setup.Setup(self.obs, self.port)
            if on:
                done = st.add_test_cards({LEFT: self.scenes[LEFT], RIGHT: self.scenes[RIGHT]},
                                         lambda end: "http://127.0.0.1:%d/testcard?end=%s" % (self.port, end))
                if self.auto_setup:
                    done += self._run_setup(st)
            else:
                done = st.remove_test_cards()
            self.setup_error = ""
        except Exception as e:
            self.setup_error = str(e)
            self.log("Director: test cameras failed: %s" % e)
            return []
        self.setup_done = done or ["test cameras already %s" % ("in place" if on else "removed")]
        for d in done:
            self._note("Test cameras: " + d)
        self.refresh_scenes()
        return done

    def on_obs_connect(self):
        if self.auto_setup:
            self.setup_obs()
        self.refresh_scenes()

    def refresh_scenes(self):
        try:
            r = self.obs.request("GetCurrentProgramScene")
            name = r.get("sceneName") or r.get("currentProgramSceneName")
            have = [s.get("sceneName") for s in self.obs.request("GetSceneList").get("scenes", [])]
        except Exception as e:
            self.log("Director: could not read OBS scenes: %s" % e)
            return
        with self.lock:
            self.on_program_changed(name)
            missing = [s for s in self.scenes.values() if s not in have]
            new_warning = missing and missing != self.missing_scenes
            self.missing_scenes = missing
        if new_warning:
            self.log("Director: WARNING - OBS has no scene called %s. Create it, or set the names with "
                     "--scene-left / --scene-right / --scene-board." % ", ".join('"%s"' % s for s in missing))

    def on_obs_event(self, etype, data):
        if etype == "CurrentProgramSceneChanged":
            self.on_program_changed(data.get("sceneName"))
        elif etype in ("SceneCreated", "SceneRemoved", "SceneNameChanged"):
            self.refresh_scenes()
        elif etype == "SceneItemCreated" and self.auto_setup and self.is_camera(data.get("sceneName")):
            # something new (e.g. the camera feed) was added to a camera scene: keep the bar above it
            try:
                if obs_setup.Setup(self.obs, self.port).keep_on_top(data["sceneName"]):
                    self._note('Score bar kept on top of "%s"' % data["sceneName"])
            except Exception as e:
                self.log("Director: %s" % e)

    def on_program_changed(self, name):
        with self.lock:
            self.program = name
            if self.is_camera(name):
                self.last_camera = name
            if self.board_active and name != self.scenes["board"]:
                self.board_active = False           # the operator took over
                self.board_until = None

    # ------------------------------------------------------------------ scoreboard events
    def sync(self, values):
        """Take the current scoreboard values without acting on them (start-up, reset)."""
        with self.lock:
            self.overs = num(values.get("overs"))
            self.wickets = num(values.get("wickets"))
            self.second_innings = bool((values.get("first_inns") or "").strip())

    def on_value(self, name, old, new):
        if name not in ("overs", "wickets", "first_inns"):
            return
        with self.lock:
            if name == "overs":
                n, o = num(new), self.overs
                self.overs = n
                if n == o:
                    return
                if n == 0 and o > 0:
                    return          # innings reset; the next "end bowling now" press sets the camera
                self._follow("Over %d complete" % n)
            elif name == "wickets":
                n, o = num(new), self.wickets
                self.wickets = n
                if n > o:
                    self._board(self.board_seconds, "Wicket (%d down)" % n)
            elif name == "first_inns":
                now_second = bool((new or "").strip())
                if now_second and not self.second_innings:
                    self.second_innings = True
                    self.start_end = ""             # unknown until the operator says
                    self._board(None, "End of innings")
                    self._changed()
                elif not now_second and self.second_innings:
                    self.second_innings = False
                    self._changed()

    def _follow(self, why):
        target = self.target_camera()
        if not self.auto or not target or self.board_active:
            return                  # (while the board is up, the return goes to the new end)
        if self.is_camera(self.program) and self.program != target:
            self._cut(target, "%s, %s end bowling" % (why, self.bowling_end()))

    def _board(self, seconds, why, force=False):
        board = self.scenes["board"]
        if not force:
            if not self.auto:
                return
            if not (self.is_camera(self.program) or (self.board_active and self.program == board)):
                return              # a break/holding scene is up: leave it
        if self.board_active and self.board_until is None and seconds is not None and not force:
            return                  # already held (end of innings)
        if self.program != board and not self._cut(board, why):
            return
        self.board_active = True
        self.board_until = None if seconds is None else self.clock() + seconds

    def tick(self):
        with self.lock:
            if self.board_active and self.board_until is not None and self.clock() >= self.board_until:
                self.board_active = False
                self.board_until = None
                if self.program == self.scenes["board"]:
                    self._cut(self.target_camera() or self.last_camera, "Back to play")

    def notify(self, name, old, new):
        """A scoreboard value changed. Once started, handled on the director's own thread so a slow
        OBS never holds up the radio decoder."""
        if self._started:
            self._queue.put((name, old, new))
        else:
            self.on_value(name, old, new)

    def start(self):
        def loop():
            while True:
                try:
                    item = self._queue.get(timeout=0.2)
                    self.on_value(*item)
                except queue.Empty:
                    pass
                except Exception as e:
                    self.log("director: %s" % e)
                try:
                    self.tick()
                except Exception as e:
                    self.log("director: %s" % e)
        self._started = True
        threading.Thread(target=loop, daemon=True, name="director").start()
        return self

    # ------------------------------------------------------------------ operator actions
    def set_bowling(self, end):
        """'end' is bowling the current over: set the starting end and cut to its camera."""
        if end not in (LEFT, RIGHT):
            raise ValueError("end must be left or right")
        with self.lock:
            self.start_end = end if self.overs % 2 == 0 else other_end(end)
            self.board_active, self.board_until = False, None
            self._changed()
            self._cut(self.scenes[end], "%s end bowling" % end.capitalize())

    def swap_ends(self):
        with self.lock:
            if not self.start_end:
                return
            self.start_end = other_end(self.start_end)
            self._changed()
            if self.is_camera(self.program) or self.board_active:
                self.board_active, self.board_until = False, None
                self._cut(self.target_camera(), "Ends swapped")

    def set_batting_first(self, team):
        if team not in (HOME, AWAY, ""):
            raise ValueError("team must be home or away")
        with self.lock:
            self.batting_first = team
            self._note("%s batting first" % (team.capitalize() if team else "Nobody"))
            self._changed()

    def set_auto(self, value):
        with self.lock:
            self.auto = (not self.auto) if value == "toggle" else bool(value)
            self._note("Auto switching %s" % ("on" if self.auto else "off"))
            self._changed()

    def go_live(self):
        with self.lock:
            self.board_active, self.board_until = False, None
            self._cut(self.target_camera() or self.last_camera or self.scenes[LEFT], "Back to play")

    def cut_to(self, scene):
        """Any other scene (breaks, holding screens). The director then leaves it alone."""
        if not scene:
            raise ValueError("scene name missing")
        with self.lock:
            self.board_active, self.board_until = False, None
            self._cut(scene, "Scene")

    def show_board(self, seconds=None, hold=False):
        with self.lock:
            self._board(None if hold else (seconds or self.board_seconds), "Full board", force=True)

    def reset_match(self):
        with self.lock:
            self.batting_first = ""
            self.start_end = ""
            self.second_innings = False
            self.overs = self.wickets = 0
            self.board_active, self.board_until = False, None
            self._note("New match: batting side and bowling end cleared")
            self._changed()

    # ------------------------------------------------------------------ status
    def status(self):
        with self.lock:
            remaining = None
            if self.board_active and self.board_until is not None:
                remaining = max(0.0, round(self.board_until - self.clock(), 1))
            return {
                "auto": self.auto, "batting_first": self.batting_first, "batting": self.batting(),
                "second_innings": self.second_innings, "start_end": self.start_end,
                "bowling_end": self.bowling_end(), "overs": self.overs, "wickets": self.wickets,
                "target_scene": self.target_camera(), "program": self.program,
                "board_active": self.board_active, "board_hold": self.board_active and self.board_until is None,
                "board_remaining": remaining, "board_seconds": self.board_seconds,
                "scenes": dict(self.scenes), "missing_scenes": list(self.missing_scenes),
                "setup": {"auto": self.auto_setup, "done": list(self.setup_done), "error": self.setup_error},
                "obs": {"enabled": self.obs is not None,
                        "connected": self._obs_ok(),
                        "error": getattr(self.obs, "error", "") if self.obs else "OBS control is off (--no-obs)"},
                "history": list(self.history[-12:]),
            }
