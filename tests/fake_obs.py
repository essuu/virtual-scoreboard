"""A small in-memory model of OBS (scenes, sources, scene items) answering obs-websocket requests."""


class OBSRequestFailed(Exception):
    pass


class ModelOBS:
    connected = True
    error = ""

    def __init__(self, scenes=(), canvas=(1920, 1080)):
        self.canvas = canvas
        self.scenes = {}            # name -> list of items, bottom first
        self.inputs = {}            # name -> {"kind": ..., "settings": {...}}
        self.program = None
        self.log = []
        self._next_id = 1
        for s in scenes:
            self.scenes[s] = []
        if scenes:
            self.program = scenes[0]

    # helpers for setting up a test
    def add_source(self, scene, name, kind="dshow_input", settings=None):
        self.inputs[name] = {"kind": kind, "settings": dict(settings or {})}
        return self.add_item(scene, name)

    def add_item(self, scene, source):
        item = {"sceneItemId": self._next_id, "sourceName": source}
        self._next_id += 1
        self.scenes[scene].append(item)
        return item["sceneItemId"]

    def names(self, scene):
        return [i["sourceName"] for i in self.scenes[scene]]

    def request(self, rtype, data=None, timeout=3.0):
        d = data or {}
        self.log.append((rtype, d))
        if rtype == "GetVideoSettings":
            return {"baseWidth": self.canvas[0], "baseHeight": self.canvas[1]}
        if rtype == "GetSceneList":
            return {"scenes": [{"sceneName": n} for n in self.scenes]}
        if rtype == "CreateScene":
            if d["sceneName"] in self.scenes or d["sceneName"] in self.inputs:
                raise OBSRequestFailed("name in use")
            self.scenes[d["sceneName"]] = []
            return {}
        if rtype == "GetInputList":
            return {"inputs": [{"inputName": n, "inputKind": v["kind"]} for n, v in self.inputs.items()
                               if "inputKind" not in d or v["kind"] == d["inputKind"]]}
        if rtype == "GetInputSettings":
            return {"inputSettings": dict(self.inputs[d["inputName"]]["settings"])}
        if rtype == "CreateInput":
            if d["inputName"] in self.inputs or d["inputName"] in self.scenes:
                raise OBSRequestFailed("name in use")
            return {"sceneItemId": self.add_source(d["sceneName"], d["inputName"], d["inputKind"],
                                                   d.get("inputSettings"))}
        if rtype == "CreateSceneItem":
            if d["sourceName"] not in self.inputs and d["sourceName"] not in self.scenes:
                raise OBSRequestFailed("no such source")
            return {"sceneItemId": self.add_item(d["sceneName"], d["sourceName"])}
        if rtype == "GetSceneItemList":
            if d["sceneName"] not in self.scenes:
                raise OBSRequestFailed("no such scene")
            out = []
            for idx, it in enumerate(self.scenes[d["sceneName"]]):
                src = it["sourceName"]
                is_scene = src in self.scenes
                out.append({"sceneItemId": it["sceneItemId"], "sourceName": src, "sceneItemIndex": idx,
                            "sourceType": "OBS_SOURCE_TYPE_SCENE" if is_scene else "OBS_SOURCE_TYPE_INPUT",
                            "inputKind": None if is_scene else self.inputs[src]["kind"]})
            return {"sceneItems": out}
        if rtype == "SetSceneItemIndex":
            items = self.scenes[d["sceneName"]]
            it = next(i for i in items if i["sceneItemId"] == d["sceneItemId"])
            items.remove(it)
            items.insert(d["sceneItemIndex"], it)
            return {}
        if rtype == "GetCurrentProgramScene":
            return {"sceneName": self.program, "currentProgramSceneName": self.program}
        if rtype == "SetCurrentProgramScene":
            self.program = d["sceneName"]
            return {}
        raise AssertionError("unexpected request " + rtype)
