"""Split one exported people base into a base container and one container per wearable.

Every output keeps the same skeleton nodes and inverse bind matrices, so the runtime can bind a
wearable to the base's bones by name. Only core glTF 2.0 encodings are used: skin weights become
normalized unsigned bytes and texture coordinates normalized unsigned shorts, which needs no
extension and no decoder. Morph normal deltas are kept on the body alone.
"""

import struct

if __package__:
    from .glb import COMPONENT, WIDTH, BinaryBuilder, accessor_values, read_glb, write_glb
else:
    from glb import COMPONENT, WIDTH, BinaryBuilder, accessor_values, read_glb, write_glb

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


def _encode(values, component):
    code, _ = COMPONENT[component]
    return struct.pack(f"<{len(values)}{code}", *values)


def _quantize_weights(values):
    out = []
    for i in range(0, len(values), 4):
        weights = values[i : i + 4]
        total = sum(weights)
        if total <= 0:
            out.extend([255, 0, 0, 0])
            continue
        scaled = [w / total * 255 for w in weights]
        rounded = [round(s) for s in scaled]
        rounded[max(range(4), key=lambda k: scaled[k])] += 255 - sum(rounded)
        if min(rounded) < 0:
            raise ValueError("weight quantization produced a negative weight")
        out.extend(rounded)
    return out


class Writer:
    def __init__(self, source, binary):
        self.source = source
        self.binary = binary
        self.buffer = BinaryBuilder()
        self.doc = {
            "asset": {"version": "2.0", "generator": "exulanica people split/1"},
            "accessors": [],
            "bufferViews": self.buffer.views,
            "buffers": [],
            "materials": [],
            "meshes": [],
            "nodes": [],
            "scene": 0,
            "scenes": [{"name": "Scene", "nodes": []}],
            "skins": [],
        }
        self.node_map = {}

    def _view(self, payload, target=None):
        return self.buffer.add(payload, target)

    def copy_accessor(self, index, component=None, normalized=False, target=None):
        src = self.source["accessors"][index]
        component = component or src["componentType"]
        out = {"componentType": component, "count": src["count"], "type": src["type"]}
        if normalized:
            out["normalized"] = True
        for key in ("min", "max"):
            if key in src and component == src["componentType"]:
                out[key] = src[key]
        if "bufferView" in src:
            values = accessor_values(self.source, self.binary, index)
            if src["type"] == "VEC4" and component == 5121 and normalized:
                values = _quantize_weights(values)
            elif component == 5123 and normalized:
                if min(values) < 0 or max(values) > 1:
                    raise ValueError("normalized texture coordinates must lie in [0, 1]")
                values = [round(v * 65535) for v in values]
            elif component in (5121, 5123, 5125) and src["componentType"] == 5126:
                values = [round(v) for v in values]
            out["bufferView"] = self._view(_encode(values, component), target)
        if "sparse" in src:
            sparse = src["sparse"]
            if component != src["componentType"]:
                raise ValueError("sparse accessors are copied without re-encoding")
            index_view = self.source["bufferViews"][sparse["indices"]["bufferView"]]
            value_view = self.source["bufferViews"][sparse["values"]["bufferView"]]

            def raw(view, offset=0):
                start = view.get("byteOffset", 0) + offset
                return bytes(self.binary[start : start + view["byteLength"] - offset])

            out["sparse"] = {
                "count": sparse["count"],
                "indices": {
                    "bufferView": self._view(raw(index_view, sparse["indices"].get("byteOffset", 0))),
                    "componentType": sparse["indices"]["componentType"],
                },
                "values": {
                    "bufferView": self._view(raw(value_view, sparse["values"].get("byteOffset", 0)))
                },
            }
        self.doc["accessors"].append(out)
        return len(self.doc["accessors"]) - 1

    def copy_skeleton(self, root_index, skin_index):
        """Copy the armature node, its joint hierarchy and the skin; return the skin index."""
        nodes = self.source["nodes"]
        root = nodes[root_index]
        joints = set(self.source["skins"][skin_index]["joints"])

        def visit(index):
            node = nodes[index]
            out = {k: v for k, v in node.items() if k in ("name", "translation", "rotation", "scale")}
            new_index = len(self.doc["nodes"])
            self.doc["nodes"].append(out)
            self.node_map[index] = new_index
            children = [c for c in node.get("children", []) if c in joints or "mesh" not in nodes[c]]
            children = [c for c in children if "mesh" not in nodes[c]]
            if children:
                out["children"] = [visit(c) for c in children]
            return new_index

        rig = {k: v for k, v in root.items() if k in ("name", "translation", "rotation", "scale")}
        rig_index = len(self.doc["nodes"])
        self.doc["nodes"].append(rig)
        self.doc["scenes"][0]["nodes"].append(rig_index)
        rig["children"] = [visit(c) for c in root.get("children", []) if "mesh" not in nodes[c]]
        skin = self.source["skins"][skin_index]
        self.doc["skins"].append(
            {
                "inverseBindMatrices": self.copy_accessor(skin["inverseBindMatrices"]),
                "joints": [self.node_map[j] for j in skin["joints"]],
                "name": skin.get("name", "skeleton"),
            }
        )
        self.rig_index = rig_index
        return len(self.doc["skins"]) - 1

    def copy_mesh_node(self, node_index, skin, keep_normal_targets, hide_attribute):
        node = self.source["nodes"][node_index]
        mesh = self.source["meshes"][node["mesh"]]
        primitives = []
        for primitive in mesh["primitives"]:
            attributes = {}
            for key, index in primitive["attributes"].items():
                if key == "WEIGHTS_0":
                    attributes[key] = self.copy_accessor(index, 5121, True, ARRAY_BUFFER)
                elif key == "TEXCOORD_0":
                    values = accessor_values(self.source, self.binary, index)
                    if min(values) >= 0 and max(values) <= 1:
                        attributes[key] = self.copy_accessor(index, 5123, True, ARRAY_BUFFER)
                    else:
                        # Coordinates outside the unit square keep their float encoding.
                        attributes[key] = self.copy_accessor(index, target=ARRAY_BUFFER)
                elif key == "_HIDE":
                    if hide_attribute:
                        attributes[key] = self.copy_accessor(index, 5123, False, ARRAY_BUFFER)
                else:
                    attributes[key] = self.copy_accessor(index, target=ARRAY_BUFFER)
            out = {
                "attributes": attributes,
                "indices": self.copy_accessor(primitive["indices"], target=ELEMENT_ARRAY_BUFFER),
                "mode": primitive.get("mode", 4),
            }
            if "material" in primitive:
                material = self.source["materials"][primitive["material"]]
                self.doc["materials"].append({"name": material["name"]})
                out["material"] = len(self.doc["materials"]) - 1
            if "targets" in primitive:
                out["targets"] = []
                for target in primitive["targets"]:
                    copied = {"POSITION": self.copy_accessor(target["POSITION"])}
                    if keep_normal_targets and "NORMAL" in target:
                        copied["NORMAL"] = self.copy_accessor(target["NORMAL"])
                    out["targets"].append(copied)
            primitives.append(out)
        out_mesh = {"name": node["name"], "primitives": primitives}
        if "weights" in mesh:
            out_mesh["weights"] = mesh["weights"]
        if "extras" in mesh:
            out_mesh["extras"] = mesh["extras"]
        self.doc["meshes"].append(out_mesh)
        new_node = {"name": node["name"], "mesh": len(self.doc["meshes"]) - 1, "skin": skin}
        self.doc["nodes"].append(new_node)
        self.doc["nodes"][self.rig_index].setdefault("children", []).append(
            len(self.doc["nodes"]) - 1
        )

    def copy_animations(self):
        self.doc["animations"] = []
        for animation in self.source.get("animations", []):
            samplers = []
            cache = {}
            for sampler in animation["samplers"]:
                entry = {}
                for key in ("input", "output"):
                    if sampler[key] not in cache:
                        cache[sampler[key]] = self.copy_accessor(sampler[key])
                    entry[key] = cache[sampler[key]]
                entry["interpolation"] = sampler.get("interpolation", "LINEAR")
                samplers.append(entry)
            channels = [
                {"sampler": c["sampler"], "target": {"node": self.node_map[c["target"]["node"]], "path": c["target"]["path"]}}
                for c in animation["channels"]
            ]
            self.doc["animations"].append({"name": animation["name"], "channels": channels, "samplers": samplers})

    def finish(self):
        data = bytes(self.buffer.data)
        self.doc["buffers"] = [{"byteLength": len(data) + (-len(data) % 4)}]
        if not self.doc["materials"]:
            del self.doc["materials"]
        return write_glb(self.doc, data)


def split_base(data, base_nodes):
    """Return {"base": bytes, <node name>: bytes} for one exported base.

    ``base_nodes`` names the mesh nodes that stay in the base container (body and face parts).
    """
    source, binary = read_glb(data)
    nodes = source["nodes"]
    root_index = source["scenes"][source.get("scene", 0)]["nodes"][0]
    mesh_nodes = [i for i in nodes[root_index].get("children", []) if "mesh" in nodes[i]]
    names = {nodes[i]["name"]: i for i in mesh_nodes}
    missing = set(base_nodes) - set(names)
    if missing:
        raise ValueError(f"base nodes missing from export: {sorted(missing)}")
    outputs = {}
    writer = Writer(source, binary)
    skin = writer.copy_skeleton(root_index, 0)
    for name in base_nodes:
        writer.copy_mesh_node(names[name], skin, keep_normal_targets=name == "body", hide_attribute=name == "body")
    writer.copy_animations()
    outputs["base"] = writer.finish()
    for name, index in sorted(names.items()):
        if name in base_nodes:
            continue
        writer = Writer(source, binary)
        skin = writer.copy_skeleton(root_index, 0)
        writer.copy_mesh_node(index, skin, keep_normal_targets=False, hide_attribute=False)
        outputs[name] = writer.finish()
    return outputs


def hide_mask_triangles(data):
    """Per hide bit, the body triangle indices a wearable covers (any covered corner hides it)."""
    document, binary = read_glb(data)
    body = next(m for m in document["meshes"] if m["name"] == "body")
    primitive = body["primitives"][0]
    hide = accessor_values(document, binary, primitive["attributes"]["_HIDE"])
    indices = accessor_values(document, binary, primitive["indices"])
    triangles = {}
    for t in range(len(indices) // 3):
        mask = int(hide[indices[3 * t]]) | int(hide[indices[3 * t + 1]]) | int(hide[indices[3 * t + 2]])
        bit = 0
        while mask:
            if mask & 1:
                triangles.setdefault(bit, []).append(t)
            mask >>= 1
            bit += 1
    return triangles, len(indices) // 3


__all__ = ["WIDTH", "hide_mask_triangles", "split_base"]
