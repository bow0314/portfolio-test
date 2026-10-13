"""AirPods 5〈世界同樂〉— Blender 場景、運鏡與渲染。

用法（背景執行，不開介面）：
  blender -b -P scene.py -- --shots 1,2 --out FRAMES_DIR [--scale 0.5] [--samples 16] [--step 1]

每鏡輸出 FRAMES_DIR/shotNN/0000.png…，並把對話泡泡的錨點（畫面座標）
寫到 FRAMES_DIR/shotNN/anchors.json，給 compose.py 用。
"""
import bpy, bmesh, math, json, os, sys, random
from mathutils import Vector, Euler, Matrix, noise
from bpy_extras.object_utils import world_to_camera_view

HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, "timeline.json"), encoding="utf-8"))
FPS = TL["fps"]
BEAT = 60.0 / TL["bpm"]

# ---------------------------------------------------------------- 參數
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default):
    return argv[argv.index(name) + 1] if name in argv else default
SHOTS = [int(s) for s in arg("--shots", "1").split(",")]
OUT = arg("--out", os.path.join(HERE, "frames"))
SCALE = float(arg("--scale", "1"))
SAMPLES = int(arg("--samples", "16"))
STEP = int(arg("--step", "1"))
ONLY = arg("--frames", "")  # 例如 "0,48,95"：只渲染指定格（預覽用）
ANCHORS_ONLY = "--anchors-only" in argv  # 只算泡泡／閃光錨點，不渲染
SHARD = [int(x) for x in arg("--shard", "0/1").split("/")]  # i/n：只渲染 f % n == i 的格，多個 Blender 並行用

# ---------------------------------------------------------------- 小工具
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def lerp(a, b, t): return a + (b - a) * t
def vlerp(a, b, t): return Vector(a).lerp(Vector(b), t)
def smooth(t): t = clamp(t); return t * t * (3 - 2 * t)
def ease_out(t): t = clamp(t); return 1 - (1 - t) ** 3
def ease_in(t): t = clamp(t); return t ** 3
def ease_io(t): t = clamp(t); return 4 * t ** 3 if t < .5 else 1 - (-2 * t + 2) ** 3 / 2
def back_out(t, s=1.9):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1
def seg(t, a, b): return clamp((t - a) / (b - a))
def bounce(t):  # 隨拍子的小彈跳，0..1
    return abs(math.sin(math.pi * t / BEAT))

def hexcol(h, a=1.0):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return (*c, a)

# ---------------------------------------------------------------- 清場
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COLL = {}
def coll(name):
    if name not in COLL:
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
        COLL[name] = c
    return COLL[name]

def link(obj, cname):
    for c in obj.users_collection: c.objects.unlink(obj)
    coll(cname).objects.link(obj)
    return obj

def mesh_obj(name, bm, cname, mats=(), smooth_shade=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    for m in mats: me.materials.append(m)
    if smooth_shade:
        for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    coll(cname).objects.link(ob)
    return ob

# ---------------------------------------------------------------- 材質
def mat(name, color, rough=0.5, metal=0.0, coat=0.0, emit=None, emit_strength=0.0,
        alpha=1.0, transmission=0.0, ior=1.45):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = hexcol(color) if isinstance(color, str) else color
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["IOR"].default_value = ior
    if "Coat Weight" in p.inputs: p.inputs["Coat Weight"].default_value = coat
    if "Transmission Weight" in p.inputs: p.inputs["Transmission Weight"].default_value = transmission
    if emit:
        p.inputs["Emission Color"].default_value = hexcol(emit) if isinstance(emit, str) else emit
        p.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1.0 or transmission > 0:
        p.inputs["Alpha"].default_value = alpha
        m.blend_method = "BLEND"
        m.shadow_method = "HASHED"
        m.use_screen_refraction = transmission > 0
        m.show_transparent_back = False
    return m

M = {}
M["white"] = mat("Plastic_White", "#F4F4F1", rough=0.22, coat=0.6)
M["white_in"] = mat("Plastic_Inner", "#E9E7E2", rough=0.4)
M["grille"] = mat("Speaker_Grille", "#55575D", rough=0.65, metal=0.5)
M["chrome"] = mat("Chrome", "#C9CCD2", rough=0.18, metal=1.0)
M["dark"] = mat("Dark", "#2A2B30", rough=0.4)
M["well"] = mat("Case_Well", "#BFBAB0", rough=0.6)
M["led"] = mat("LED", "#7BFF9E", emit="#7BFF9E", emit_strength=0.0)
M["glow"] = mat("Warm_Glow", "#FFD7A0", emit="#FFC680", emit_strength=0.0)
M["ring"] = mat("Bud_Glow", "#9AD8FF", emit="#9AD8FF", emit_strength=0.0, alpha=0.9)
M["ocean"] = mat("Ocean", "#3BA7E0", rough=0.35)
M["land"] = mat("Land", "#7FD06B", rough=0.8)
M["land2"] = mat("Land_Dark", "#4DB26A", rough=0.8)
M["sand"] = mat("Sand", "#F3D99B", rough=0.9)
M["snow"] = mat("Snow", "#FFFFFF", rough=0.7)
M["tree"] = mat("Tree", "#2F9E5B", rough=0.8)
M["trunk"] = mat("Trunk", "#9B6A43", rough=0.8)
M["cloud"] = mat("Cloud", "#FFFFFF", rough=0.9)
M["water"] = mat("Sea_Water", "#36C4D9", rough=0.12, coat=0.5)
M["splash"] = mat("Splash", (0.75, 0.93, 1.0, 1), rough=0.05, alpha=0.55, transmission=0.6, ior=1.33)
M["marker"] = mat("Marker", "#FFE45C", emit="#FFE45C", emit_strength=0.0)
M["halo"] = mat("Halo", "#FFFFFF", emit="#FFFFFF", emit_strength=0.0, alpha=0.85)
M["eye"] = mat("Eye", "#1A1A1A", rough=0.3)
M["cheek"] = mat("Cheek", "#FF9AA8", rough=0.8)
M["bulb"] = [mat(f"Bulb_{i}", c, emit=c, emit_strength=4.0)
             for i, c in enumerate(["#FFD25C", "#FF7A8A", "#7FE3FF", "#B78CFF", "#9CFF8A"])]
PALETTE = ["#FF6F61", "#FFB547", "#FFD93D", "#6BCB77", "#4D96FF", "#B983FF", "#FF8FB1", "#2EC4B6"]
def pmat(c, rough=0.6):
    key = f"P_{c}_{rough}"
    if key not in M: M[key] = mat(key, c, rough=rough)
    return M[key]
SKIN = ["#F6D1B5", "#E0AC80", "#B47A55", "#8D5A3B", "#FFE0C7"]

# ---------------------------------------------------------------- 幾何
def bm_sphere(r=1.0, seg=32, ring=16, loc=(0, 0, 0), scale=(1, 1, 1), ico=0):
    bm = bmesh.new()
    if ico:
        bmesh.ops.create_icosphere(bm, subdivisions=ico, radius=r)
    else:
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=ring, radius=r)
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    bmesh.ops.translate(bm, vec=loc, verts=bm.verts)
    return bm

def bm_cyl(r1, r2, depth, seg=32, loc=(0, 0, 0), scale=(1, 1, 1), rot=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r1, radius2=r2, depth=depth)
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    if rot: bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Euler(rot).to_matrix())
    bmesh.ops.translate(bm, vec=loc, verts=bm.verts)
    return bm

def bm_box(size, loc=(0, 0, 0), bevel=0.0, segs=4):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges) + list(bm.verts), offset=bevel, segments=segs,
                        profile=0.5, affect="EDGES", clamp_overlap=True)
    bmesh.ops.translate(bm, vec=loc, verts=bm.verts)
    return bm

def bm_merge(*bms):
    out = bmesh.new()
    me = bpy.data.meshes.new("_tmp")
    for b in bms:
        b.to_mesh(me); b.free()
        out.from_mesh(me)
    bpy.data.meshes.remove(me)
    return out

def part(name, bm, material, cname, parent=None, smooth_shade=True):
    ob = mesh_obj(name, bm, cname, [material], smooth_shade)
    if parent: ob.parent = parent
    return ob

def remesh(ob, voxel=0.03, smooth_iter=6):
    m = ob.modifiers.new("vox", "REMESH"); m.mode = "VOXEL"; m.voxel_size = voxel
    s = ob.modifiers.new("sm", "SMOOTH"); s.iterations = smooth_iter; s.factor = 0.5
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    for mod in ("vox", "sm"):
        bpy.ops.object.modifier_apply(modifier=mod)
    ob.select_set(False)
    for p in ob.data.polygons: p.use_smooth = True

def empty(name, cname, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.location = loc
    coll(cname).objects.link(e)
    return e

# ---------------------------------------------------------------- 耳機
def make_bud(side):
    """side = +1 左耳（音孔朝 +X），-1 右耳。原點在耳機頭中心，柄朝 -Z。"""
    root = empty(f"Bud_{'L' if side > 0 else 'R'}", "buds")
    head = bm_sphere(1.0, 48, 24, scale=(0.95, 0.86, 0.80))
    bmesh.ops.rotate(head, verts=head.verts, cent=(0, 0, 0), matrix=Euler((0.25, 0, 0.2 * side)).to_matrix())
    stem = bm_cyl(0.30, 0.27, 2.9, 32, loc=(0, 0.18, -1.75), scale=(1, 0.82, 1), rot=(-0.08, 0, 0))
    foot = bm_sphere(0.27, 32, 16, loc=(0, 0.30, -3.18), scale=(1, 0.82, 0.7))
    shell = part(root.name + "_shell", bm_merge(head, stem, foot), M["white"], "buds", root)
    remesh(shell, 0.028, 5)
    # 音孔網：貼在頭部內側、略朝前
    d = Vector((0.62 * side, -0.55, 0.15)).normalized()
    g = part(root.name + "_grille", bm_cyl(0.30, 0.27, 0.07, 40, scale=(1, 0.7, 1)), M["grille"], "buds", root)
    g.location = d * 0.80
    g.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    # 感測器小黑點、柄底麥克風
    s = part(root.name + "_sensor", bm_cyl(0.09, 0.09, 0.04, 20), M["dark"], "buds", root)
    d2 = Vector((0.2 * side, 0.75, 0.45)).normalized()
    s.location = d2 * 0.83
    s.rotation_euler = d2.to_track_quat("Z", "Y").to_euler()
    mic = part(root.name + "_mic", bm_cyl(0.16, 0.16, 0.05, 24, scale=(1, 0.8, 1)), M["chrome"], "buds", root)
    mic.location = (0, 0.30, -3.37)
    # 降噪啟動時的光環（平常看不到）
    ring = bmesh.new()
    bmesh.ops.create_circle(ring, cap_ends=False, segments=48, radius=1.0)
    ringo = part(root.name + "_ring", ring, M["ring"], "buds", root, smooth_shade=False)
    ringo.scale = (0, 0, 0)
    return root

def make_ring_torus(name, cname, material, major=1.0, minor=0.04):
    bm = bmesh.new()
    segs, ring = 96, 12
    verts = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        row = []
        for j in range(ring):
            b = 2 * math.pi * j / ring
            r = major + minor * math.cos(b)
            row.append(bm.verts.new((r * math.cos(a), r * math.sin(a), minor * math.sin(b))))
        verts.append(row)
    for i in range(segs):
        for j in range(ring):
            bm.faces.new((verts[i][j], verts[(i + 1) % segs][j], verts[(i + 1) % segs][(j + 1) % ring], verts[i][(j + 1) % ring]))
    return mesh_obj(name, bm, cname, [material])

BUD_L = make_bud(+1)
BUD_R = make_bud(-1)
RING_L = bpy.data.objects["Bud_L_ring"]; RING_R = bpy.data.objects["Bud_R_ring"]
for r, b in ((RING_L, BUD_L), (RING_R, BUD_R)):
    t = make_ring_torus(r.name + "_t", "buds", M["ring"], 1.25, 0.035)
    t.parent = b
    t.rotation_euler = (math.radians(90), 0, 0)
    t.scale = (0, 0, 0)
    bpy.data.objects.remove(r)
RING_L = bpy.data.objects["Bud_L_ring_t"]; RING_R = bpy.data.objects["Bud_R_ring_t"]

# ---------------------------------------------------------------- 充電盒
CASE_W, CASE_D, CASE_H, LID_H = 5.0, 2.12, 4.62, 1.15
HINGE_Y = CASE_D / 2 - 0.15
CASE = empty("Case", "case")
LID_PIVOT = empty("LidPivot", "case", (0, HINGE_Y, CASE_H - LID_H))
LID_PIVOT.parent = CASE

def case_halves():
    full = bm_box((CASE_W, CASE_D, CASE_H), (0, 0, CASE_H / 2), bevel=0.92, segs=12)
    cut = CASE_H - LID_H
    halves = []
    for keep_below in (True, False):
        bm = full.copy()
        res = bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                                     plane_co=(0, 0, cut), plane_no=(0, 0, 1),
                                     clear_outer=keep_below, clear_inner=not keep_below)
        edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        halves.append(bm)
    full.free()
    return halves

body_bm, lid_bm = case_halves()
CASE_BODY = part("Case_Body", body_bm, M["white"], "case", CASE)
bmesh.ops.translate(lid_bm, vec=(0, -HINGE_Y, -(CASE_H - LID_H)), verts=lid_bm.verts)
CASE_LID = part("Case_Lid", lid_bm, M["white"], "case", LID_PIVOT)
for ob in (CASE_BODY, CASE_LID):
    ob.data.use_auto_smooth = True
    ob.data.auto_smooth_angle = math.radians(35)
# 蓋縫細線、上方內面、兩個耳機槽、暖光、指示燈、背面樞紐
TOP_Z = CASE_H - LID_H
inner = part("Case_Inner", bm_box((CASE_W - 0.5, CASE_D - 0.4, 0.04), (0, 0, TOP_Z + 0.01), 0.15, 3), M["white_in"], "case", CASE)
for sx in (-1, 1):
    part(f"Case_Well_{sx}", bm_cyl(0.42, 0.42, 0.02, 32, loc=(1.15 * sx, 0.12, TOP_Z + 0.04), scale=(1, 0.8, 1)), M["well"], "case", CASE)
GLOW = part("Case_Glow", bm_box((CASE_W - 1.0, CASE_D - 0.7, 0.01), (0, 0, TOP_Z + 0.035), 0.1, 2), M["glow"], "case", CASE)
LED = part("Case_LED", bm_cyl(0.07, 0.07, 0.05, 20, loc=(0, -CASE_D / 2 + 0.005, TOP_Z - 0.55), rot=(math.pi / 2, 0, 0)), M["led"], "case", CASE)
GLOW_LIGHT = bpy.data.lights.new("CaseGlowLight", "POINT")
GLOW_LIGHT.color = (1.0, 0.78, 0.5); GLOW_LIGHT.energy = 0; GLOW_LIGHT.shadow_soft_size = 1.0
gl = bpy.data.objects.new("CaseGlowLight", GLOW_LIGHT); coll("case").objects.link(gl)
gl.parent = CASE; gl.location = (0, -0.2, TOP_Z + 0.6)

def bud_in_case(side):
    """耳機收在盒裡時的世界座標與旋轉（盒子在原點、無旋轉時）。"""
    return Vector((1.15 * side, 0.12, TOP_Z - 0.05)), Euler((0.35, 0, -0.5 * side))

# ---------------------------------------------------------------- 低多邊形地球
GLOBE_R = 12.0
GLOBE_C = Vector((0, 0, -GLOBE_R - 0.05))
GLOBE = empty("Globe", "globe", GLOBE_C)
def make_globe():
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=GLOBE_R)
    random.seed(7)
    land_dirs = []
    for f in bm.faces:
        c = f.calc_center_median().normalized()
        n = noise.noise(c * 1.6 + Vector((3.1, 1.7, 0.4))) + 0.5 * noise.noise(c * 3.7)
        lat = c.z
        if lat > 0.86: f.material_index = 4                          # 北極雪
        elif n > 0.18: f.material_index = 1 if n < 0.45 else 2       # 陸地
        elif n > 0.08: f.material_index = 3                          # 沙灘
        else: f.material_index = 0
        if f.material_index in (1, 2) and random.random() < 0.10:
            land_dirs.append(c)
    # 陸地微微隆起
    for v in bm.verts:
        faces = v.link_faces
        if any(f.material_index in (1, 2, 4) for f in faces):
            v.co *= 1.03
    ob = mesh_obj("Globe_Mesh", bm, "globe", [M["ocean"], M["land"], M["land2"], M["sand"], M["snow"]], smooth_shade=False)
    ob.parent = GLOBE
    # 樹
    for i, c in enumerate(land_dirs[:70]):
        if c.z > 0.97: continue
        t = part(f"Tree_{i}", bm_cyl(0.45, 0.0, 1.3, 6, loc=(0, 0, 0.9)), M["tree"], "globe", GLOBE, False)
        t.location = c * GLOBE_R * 1.02
        t.rotation_euler = c.to_track_quat("Z", "Y").to_euler()
        s = 0.7 + 0.6 * random.random(); t.scale = (s, s, s)
    # 雲
    clouds = []
    for i in range(9):
        c = Vector((random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-0.6, 0.7))).normalized()
        cl = part(f"Cloud_{i}", bm_merge(bm_sphere(0.9, ico=1), bm_sphere(0.7, ico=1, loc=(0.9, 0, -0.1)),
                                       bm_sphere(0.6, ico=1, loc=(-0.85, 0.1, -0.15))), M["cloud"], "globe", GLOBE, False)
        cl.location = c * (GLOBE_R + 2.2)
        cl.rotation_euler = c.to_track_quat("Z", "X").to_euler()
        clouds.append((cl, c))
    return ob, clouds
GLOBE_MESH, CLOUDS = make_globe()
# 三座城市在地球上的方向（市集、海灘、樂團），與亮點、光環
CITY_DIRS = [Vector(d).normalized() for d in ((0.55, -0.75, 0.38), (-0.25, -0.9, -0.2), (-0.8, -0.45, 0.35))]
MARKERS = []
for i, d in enumerate(CITY_DIRS):
    mk = part(f"Marker_{i}", bm_sphere(0.55, ico=2), M["marker"], "globe", GLOBE)
    mk.location = d * (GLOBE_R + 0.5)
    mk.scale = (0, 0, 0)
    MARKERS.append(mk)
HALO = make_ring_torus("Halo", "globe", M["halo"], GLOBE_R + 0.6, 0.12)
HALO.parent = GLOBE
_n = CITY_DIRS[0].cross(CITY_DIRS[1]).normalized()
HALO.rotation_euler = _n.to_track_quat("Z", "Y").to_euler()
HALO.scale = (0, 0, 0)

# ---------------------------------------------------------------- 角色（豆豆人）
def make_person(name, cname, loc, color, skin, facing=0.0, scale=1.0):
    root = empty(name, cname, loc)
    root.rotation_euler = (0, 0, facing)
    root.scale = (scale,) * 3
    body = part(name + "_body", bm_merge(bm_cyl(0.42, 0.34, 1.0, 24, loc=(0, 0, 0.5)), bm_sphere(0.42, 24, 12, loc=(0, 0, 0.02), scale=(1, 1, 0.5))),
                pmat(color, 0.55), cname, root)
    head = part(name + "_head", bm_sphere(0.42, 32, 16, loc=(0, 0, 1.42)), pmat(skin, 0.6), cname, root)
    for sx in (-1, 1):
        part(f"{name}_eye{sx}", bm_sphere(0.055, 12, 8, loc=(0.14 * sx, -0.39, 1.48)), M["eye"], cname, root)
        part(f"{name}_cheek{sx}", bm_sphere(0.07, 12, 8, loc=(0.24 * sx, -0.34, 1.36), scale=(1, 0.5, 0.6)), M["cheek"], cname, root)
    return root

def island(cname, center, top_color, radius=7.0):
    part(cname + "_base", bm_cyl(radius, radius * 0.92, 1.2, 64, loc=Vector(center) + Vector((0, 0, -0.6))), pmat(top_color, 0.85), cname)
    part(cname + "_dirt", bm_cyl(radius * 0.92, radius * 0.55, 2.2, 64, loc=Vector(center) + Vector((0, 0, -2.3))), pmat("#C98F5E", 0.9), cname)

def string_lights(cname, p0, p1, sag=0.6, n=14):
    p0, p1 = Vector(p0), Vector(p1)
    for i in range(n):
        t = i / (n - 1)
        p = p0.lerp(p1, t) - Vector((0, 0, sag * 4 * t * (1 - t)))
        part(f"{cname}_bulb_{len(bpy.data.objects)}", bm_sphere(0.09, 12, 8, loc=p), M["bulb"][i % 5], cname, None)

# --- 市集
MK = Vector((200, 0, 0))
island("market", MK, "#E7C28F")
def stall(i, x, y, color, rot=0.0):
    root = empty(f"stall_{i}", "market", MK + Vector((x, y, 0)))
    root.rotation_euler = (0, 0, rot)
    part(f"stall_{i}_counter", bm_box((2.6, 1.0, 1.0), (0, 0, 0.5), 0.05, 2), pmat("#B57B4A", 0.7), "market", root)
    for sx in (-1.2, 1.2):
        part(f"stall_{i}_post{sx}", bm_cyl(0.06, 0.06, 2.4, 8, loc=(sx, 0.4, 1.2)), pmat("#8A5A35"), "market", root)
    for k in range(6):  # 條紋遮雨棚
        part(f"stall_{i}_awn{k}", bm_box((0.46, 1.5, 0.08), (-1.15 + 0.46 * k, 0.1, 2.45), 0.0), pmat(color if k % 2 == 0 else "#FFFFFF", 0.6), "market", root).rotation_euler = (-0.25, 0, 0)
    fruit = ["#FF5252", "#FFB300", "#7CB342", "#FF7043"]
    for k in range(9):
        part(f"stall_{i}_fruit{k}", bm_sphere(0.17, 16, 8, loc=(-1.0 + 0.25 * k, -0.15 + 0.12 * (k % 2), 1.12)), pmat(fruit[k % 4], 0.45), "market", root)
    return root
stall(0, 0.0, 1.6, "#FF6F61")
stall(1, -3.6, 0.6, "#4D96FF", 0.45)
stall(2, 3.6, 0.6, "#6BCB77", -0.45)
string_lights("market", MK + Vector((-5.5, 2.5, 3.6)), MK + Vector((5.5, 2.5, 3.6)), 0.9, 18)
string_lights("market", MK + Vector((-5.0, -1.0, 3.2)), MK + Vector((5.0, -1.0, 3.2)), 0.7, 16)
for k, x in enumerate((-5.5, 5.5)):
    part(f"market_pole{k}", bm_cyl(0.08, 0.08, 4.0, 8, loc=MK + Vector((x, 2.5, 2.0))), pmat("#6E4A2E"), "market")
VENDOR = make_person("vendor", "market", MK + Vector((0.2, 2.6, 0)), "#FFB547", SKIN[1], facing=0.0)
for i, (x, y, c, s) in enumerate(((-1.2, -1.6, "#4D96FF", SKIN[0]), (1.6, -1.2, "#B983FF", SKIN[3]), (-4.2, -2.6, "#2EC4B6", SKIN[2]))):
    make_person(f"shopper{i}", "market", MK + Vector((x, y, 0)), c, s, facing=math.pi if i < 2 else 2.6)

# --- 海灘
BC = Vector((300, 0, 0))
part("beach_sand", bm_cyl(7.5, 7.2, 1.0, 64, loc=BC + Vector((0, 2.0, -0.5))), M["sand"], "beach")
part("beach_dirt", bm_cyl(7.2, 4.0, 2.0, 64, loc=BC + Vector((0, 2.0, -2.0))), pmat("#C98F5E", 0.9), "beach")
def make_sea():
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=130, y_segments=110, size=1.0)
    bmesh.ops.scale(bm, vec=(26, 14, 1), verts=bm.verts)
    bmesh.ops.translate(bm, vec=BC + Vector((0, -11.5, -0.05)), verts=bm.verts)
    ob = mesh_obj("beach_sea", bm, "beach", [M["water"]])
    return ob
SEA = make_sea()
SEA_REST = [v.co.copy() for v in SEA.data.vertices]
def animate_sea(t, amp=0.18, wave=None):
    for v, r in zip(SEA.data.vertices, SEA_REST):
        x, y = r.x - BC.x, r.y - BC.y
        z = amp * math.sin(0.9 * x + 2.2 * t) * 0.5 + amp * math.sin(0.7 * y + 2.8 * t)
        if wave is not None:  # 一道大浪往 +y 推進
            z += wave[1] * math.exp(-((y - wave[0]) ** 2) / 1.2)
        v.co.z = r.z + z
    SEA.data.update()
# 遮陽傘
UMB = empty("umbrella", "beach", BC + Vector((-2.6, 3.0, 0)))
part("umb_pole", bm_cyl(0.06, 0.06, 3.0, 8, loc=(0, 0, 1.5)), pmat("#FFFFFF"), "beach", UMB)
for k in range(8):
    bm = bmesh.new()
    a0, a1 = k / 8 * math.tau, (k + 1) / 8 * math.tau
    top = bm.verts.new((0, 0, 3.4))
    v0 = bm.verts.new((2.0 * math.cos(a0), 2.0 * math.sin(a0), 2.6))
    v1 = bm.verts.new((2.0 * math.cos(a1), 2.0 * math.sin(a1), 2.6))
    bm.faces.new((top, v0, v1))
    part(f"umb_{k}", bm, pmat("#FF6F61" if k % 2 else "#FFFFFF", 0.6), "beach", UMB, False)
UMB.rotation_euler = (0.12, -0.1, 0)
part("beach_towel", bm_box((1.4, 2.4, 0.04), BC + Vector((-1.2, 2.2, 0.02))), pmat("#4D96FF"), "beach")
BALL = part("beach_ball", bm_sphere(0.45, 24, 12), pmat("#FFD93D", 0.35), "beach")
for k, c in enumerate(("#FF6F61", "#4D96FF")):
    s = part(f"beach_ball_stripe{k}", bm_sphere(0.455, 24, 12, scale=(1, 0.35, 1)), pmat(c, 0.35), "beach", BALL)
    s.rotation_euler = (0, 0, k * math.pi / 2)
BALL.location = BC + Vector((1.8, 0.6, 0.45))
# 椰子樹
PALM = empty("palm", "beach", BC + Vector((3.8, 4.2, 0)))
for k in range(6):
    part(f"palm_trunk{k}", bm_cyl(0.28 - 0.025 * k, 0.25 - 0.025 * k, 0.75, 10, loc=(0.12 * k * k * 0.08, 0, 0.375 + 0.7 * k)), M["trunk"], "beach", PALM, False)
for k in range(7):
    a = k / 7 * math.tau
    leaf = part(f"palm_leaf{k}", bm_sphere(1.0, 12, 6, scale=(1.7, 0.42, 0.08)), M["tree"], "beach", PALM, False)
    leaf.location = (0.3 + 1.3 * math.cos(a), 1.3 * math.sin(a), 4.2)
    leaf.rotation_euler = (0, 0.45, a)
for k in range(3):
    part(f"coconut{k}", bm_sphere(0.17, 12, 8, loc=(0.25 + 0.2 * math.cos(k * 2), 0.2 * math.sin(k * 2), 3.95)), M["trunk"], "beach", PALM)
SWIMMER = make_person("swimmer", "beach", BC + Vector((-0.6, 0.2, 0)), "#FF8FB1", SKIN[2], facing=0.25)
make_person("friend", "beach", BC + Vector((0.9, 1.4, 0)), "#4D96FF", SKIN[4], facing=-0.4)
# 太陽
SUN_DISC = part("beach_sun", bm_sphere(2.2, 32, 16), mat("SunDisc", "#FFE58A", emit="#FFE58A", emit_strength=6.0), "beach")
SUN_DISC.location = BC + Vector((8, 40, 14))

# --- 街頭樂團
BD = Vector((400, 0, 0))
island("band", BD, "#9AA5B8")
part("stage", bm_box((7.0, 3.0, 0.6), BD + Vector((0, 2.8, 0.3)), 0.08, 2), pmat("#3A3F55"), "band")
for sx in (-1, 1):
    spk = part(f"speaker{sx}", bm_box((1.0, 0.8, 1.6), BD + Vector((3.0 * sx, 3.2, 1.4)), 0.06, 2), pmat("#22242E"), "band")
    for k, z in enumerate((1.85, 1.1)):
        part(f"cone{sx}{k}", bm_cyl(0.28 - 0.08 * k, 0.28 - 0.08 * k, 0.04, 24, loc=BD + Vector((3.0 * sx, 2.79, z)), rot=(math.pi / 2, 0, 0)), M["chrome"], "band")
DRUM = part("drum", bm_cyl(0.55, 0.55, 0.6, 32, loc=BD + Vector((1.2, 3.4, 0.9))), pmat("#FF6F61", 0.3), "band")
part("drum_top", bm_cyl(0.56, 0.56, 0.02, 32, loc=BD + Vector((1.2, 3.4, 1.21))), pmat("#FFFFFF", 0.5), "band")
part("mic_stand", bm_cyl(0.03, 0.03, 1.5, 8, loc=BD + Vector((-0.6, 2.1, 1.35))), M["chrome"], "band")
part("mic", bm_sphere(0.09, 12, 8, loc=BD + Vector((-0.6, 2.05, 2.15))), M["dark"], "band")
MUSICIANS = [make_person("singer", "band", BD + Vector((-0.6, 2.6, 0.6)), "#B983FF", SKIN[0]),
             make_person("drummer", "band", BD + Vector((1.2, 4.0, 0.6)), "#FFD93D", SKIN[3]),
             make_person("guitarist", "band", BD + Vector((-2.2, 3.0, 0.6)), "#2EC4B6", SKIN[1])]
FAN = make_person("fan", "band", BD + Vector((0.6, -1.4, 0)), "#FF6F61", SKIN[4], facing=math.pi)
CROWD = [FAN] + [make_person(f"crowd{i}", "band", BD + Vector((x, y, 0)), PALETTE[i % 8], SKIN[i % 5], facing=math.pi)
                 for i, (x, y) in enumerate(((-1.6, -1.0), (-3.0, -2.2), (2.4, -2.0), (-0.6, -3.2), (3.4, -0.6)))]
for k, x in enumerate((-3.4, 3.4)):
    part(f"lamp_post{k}", bm_cyl(0.08, 0.08, 4.4, 8, loc=BD + Vector((x, 4.6, 2.2))), pmat("#22242E"), "band")
string_lights("band", BD + Vector((-3.4, 4.6, 4.3)), BD + Vector((3.4, 4.6, 4.3)), 0.8, 18)
NOTES = []
for i in range(10):
    n = empty(f"note{i}", "band")
    part(f"note{i}_head", bm_sphere(0.22, 16, 8, scale=(1.25, 0.6, 0.9)), pmat(PALETTE[i % 8], 0.4), "band", n)
    part(f"note{i}_stem", bm_box((0.06, 0.06, 0.8), (0.24, 0, 0.4)), pmat(PALETTE[i % 8], 0.4), "band", n)
    part(f"note{i}_flag", bm_box((0.28, 0.06, 0.12), (0.36, 0, 0.74)), pmat(PALETTE[i % 8], 0.4), "band", n).rotation_euler = (0, -0.5, 0)
    NOTES.append(n)
CONFETTI = []
random.seed(11)
for i in range(70):
    c = part(f"confetti{i}", bm_box((0.16, 0.08, 0.01)), pmat(PALETTE[i % 8], 0.5), "band", None, False)
    CONFETTI.append((c, Vector((random.uniform(-5, 5), random.uniform(-4, 4), random.uniform(0, 7))), random.random() * 10))

# --- 抽象攝影棚（第 7、8、9 鏡）
ST = Vector((500, 0, 0))
part("studio_floor", bm_cyl(30, 30, 0.1, 96, loc=ST + Vector((0, 0, -3.6))), pmat("#FFFFFF", 0.4), "studio")
NOISE = []
random.seed(5)
for i in range(46):
    b = bmesh.new()
    bmesh.ops.create_icosphere(b, subdivisions=1, radius=1.0)
    for v in b.verts: v.co *= random.uniform(0.75, 1.3)
    ob = part(f"noise{i}", b, pmat(["#FF4D4D", "#FF8A00", "#FFD000", "#FF3D9A", "#8C52FF", "#00C2FF"][i % 6], 0.5), "studio", None, False)
    a = random.uniform(0, math.tau); r = random.uniform(4.5, 11); h = random.uniform(-3, 5)
    NOISE.append((ob, Vector((math.cos(a) * r, math.sin(a) * r * 0.7 + 2.0, h)), random.uniform(0.35, 0.9), random.uniform(0, 10)))
DROPS = []
random.seed(9)
drop_mesh = bm_sphere(0.09, 16, 8)
_dm = bpy.data.meshes.new("drop"); drop_mesh.to_mesh(_dm); drop_mesh.free()
for p in _dm.polygons: p.use_smooth = True
_dm.materials.append(M["splash"])
for i in range(150):
    ob = bpy.data.objects.new(f"drop{i}", _dm); coll("fx").objects.link(ob)
    DROPS.append((ob, Vector((random.uniform(-1.6, 1.6), random.uniform(-1.0, 1.0), random.uniform(-2.5, 0.3))),
                  Vector((random.uniform(-3.5, 3.5), random.uniform(-2.5, 1.5), random.uniform(3.0, 8.0))),
                  random.uniform(0.6, 1.8)))
WAVE = part("wave_curl", bm_sphere(1.0, 48, 24, scale=(5.0, 1.6, 2.2)), M["water"], "studio")
SPLASH_LIGHTS = []

# ---------------------------------------------------------------- 燈光、相機、世界
def area(name, loc, target, energy, size, color=(1, 1, 1)):
    L = bpy.data.lights.new(name, "AREA"); L.energy = energy; L.size = size; L.color = color
    o = bpy.data.objects.new(name, L); scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o
KEY = area("Key", (-8, -10, 12), (0, 0, 2), 2500, 8, (1.0, 0.96, 0.9))
FILL = area("Fill", (10, -6, 4), (0, 0, 2), 900, 10, (0.9, 0.95, 1.0))
RIM = area("Rim", (0, 12, 9), (0, 0, 2), 1800, 6, (1.0, 0.9, 0.85))
SUN = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN")); scene.collection.objects.link(SUN)
SUN.data.energy = 2.5; SUN.data.angle = math.radians(8); SUN.rotation_euler = (math.radians(40), math.radians(10), math.radians(30))
LIGHT_RIG = [KEY, FILL, RIM]
RIG_OFFS = [Vector(o.location) for o in LIGHT_RIG]
RIG_ROT = [o.rotation_euler.copy() for o in LIGHT_RIG]
def rig_at(center, s=1.0):
    for o, off in zip(LIGHT_RIG, RIG_OFFS):
        o.location = Vector(center) + off * s

cam_data = bpy.data.cameras.new("Cam"); CAM = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(CAM); scene.camera = CAM
cam_data.clip_start = 0.05; cam_data.clip_end = 600
def look(loc, target, lens=50, roll=0.0, dof=None, fstop=2.8):
    CAM.location = Vector(loc)
    q = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y")
    CAM.rotation_euler = (q @ Euler((0, 0, roll)).to_quaternion()).to_euler()
    cam_data.lens = lens
    cam_data.dof.use_dof = dof is not None
    if dof is not None:
        cam_data.dof.focus_distance = dof if isinstance(dof, (int, float)) else (Vector(dof) - Vector(loc)).length
        cam_data.dof.aperture_fstop = fstop

world = bpy.data.worlds.new("World"); scene.world = world; world.use_nodes = True
wn = world.node_tree.nodes; wl = world.node_tree.links
bg = wn["Background"]
tc = wn.new("ShaderNodeTexCoord"); sep = wn.new("ShaderNodeSeparateXYZ")
mr = wn.new("ShaderNodeMapRange"); mix = wn.new("ShaderNodeMix"); mix.data_type = "RGBA"
wl.new(tc.outputs["Generated"], sep.inputs[0])
wl.new(sep.outputs["Z"], mr.inputs["Value"])
mr.inputs["From Min"].default_value = -0.3; mr.inputs["From Max"].default_value = 0.6
wl.new(mr.outputs["Result"], mix.inputs["Factor"])
wl.new(mix.outputs["Result"], bg.inputs["Color"])
def sky(bottom, top, strength=1.0):
    mix.inputs["A"].default_value = hexcol(bottom) if isinstance(bottom, str) else bottom
    mix.inputs["B"].default_value = hexcol(top) if isinstance(top, str) else top
    bg.inputs["Strength"].default_value = strength
def sky_lerp(a, b, t, strength=1.0):
    ca = [hexcol(x) for x in a]; cb = [hexcol(x) for x in b]
    sky(tuple(lerp(ca[0][i], cb[0][i], t) for i in range(4)), tuple(lerp(ca[1][i], cb[1][i], t) for i in range(4)), strength)

# ---------------------------------------------------------------- 渲染設定
r = scene.render
r.engine = "BLENDER_EEVEE"
r.resolution_x = int(TL["width"] * SCALE); r.resolution_y = int(TL["height"] * SCALE)
r.resolution_percentage = 100
r.image_settings.file_format = "PNG"; r.image_settings.color_mode = "RGB"
r.fps = FPS
ee = scene.eevee
ee.taa_render_samples = SAMPLES
ee.use_gtao = True; ee.gtao_distance = 1.5
ee.use_bloom = True; ee.bloom_intensity = 0.04; ee.bloom_threshold = 1.2
ee.use_ssr = True; ee.use_ssr_refraction = True
ee.use_soft_shadows = True
ee.shadow_cube_size = "1024"; ee.shadow_cascade_size = "2048"
scene.view_settings.view_transform = "AgX"
try: scene.view_settings.look = "AgX - Punchy"
except Exception: pass

ALL_SETS = ["buds", "case", "globe", "market", "beach", "band", "studio", "fx"]
def show(*names):
    for n in ALL_SETS:
        coll(n).hide_render = n not in names

# ---------------------------------------------------------------- 物件狀態工具
def place(ob, loc, rot=(0, 0, 0), s=1.0):
    ob.location = Vector(loc); ob.rotation_euler = Euler(rot); ob.scale = (s, s, s)

def case_state(lid_open=0.0, glow=0.0, at=(0, 0, 0), rot=(0, 0, 0)):
    CASE.location = Vector(at); CASE.rotation_euler = Euler(rot)
    LID_PIVOT.rotation_euler = (-math.radians(105) * lid_open, 0, 0)
    M["glow"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 3.0 * glow
    GLOW_LIGHT.energy = 60 * glow
    M["led"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 6.0 * glow

def buds_in_case():
    for b, sd in ((BUD_L, 1), (BUD_R, -1)):
        p, e = bud_in_case(sd); place(b, p, e, 1.0)

def bud_glow(v):
    M["ring"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 8.0 * v
    for rr in (RING_L, RING_R):
        s = 0.0 if v <= 0 else 0.9 + 0.5 * (1 - v)
        rr.scale = (s, s, s)

def person_bob(root, t, phase=0.0, amp=0.12, base_z=None):
    if base_z is None:
        base_z = root.get("z0", root.location.z); root["z0"] = base_z
    root.location.z = base_z + amp * abs(math.sin(math.pi * (t + phase) / BEAT))
    root.scale.z = root.scale.x * (1 + 0.04 * math.sin(2 * math.pi * (t + phase) / BEAT))

def head_world(root, off=(0, 0, 1.95)):
    return root.matrix_world @ Vector(off)

# ---------------------------------------------------------------- 各鏡頭
def shot1(t, f):  # 0–4s 充電盒開蓋
    show("case", "buds")
    rig_at((0, 0, 0)); SUN.data.energy = 0.0
    o = back_out(seg(t, 1.0, 1.65), 1.4)
    case_state(o, smooth(seg(t, 0.95, 1.8)))
    buds_in_case()
    lift = 0.35 * smooth(seg(t, 1.6, 3.6))
    BUD_L.location.z += lift; BUD_R.location.z += lift * 0.85
    a = lerp(-0.35, 0.1, ease_io(t / 4))
    d = lerp(19, 13.5, ease_out(t / 4))
    look((math.sin(a) * d, -math.cos(a) * d, lerp(5.5, 7.2, t / 4)), (0, 0, 2.6 + 0.4 * t / 4), 50, dof=(0, 0, 3), fstop=4)
    sky_lerp(("#140F1E", "#1E1730"), ("#FFB48A", "#FFD9B8"), smooth(seg(t, 1.0, 3.6)), lerp(0.4, 1.0, smooth(seg(t, 1, 3.6))))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)):
        o_.data.energy = base * lerp(0.35, 1.0, smooth(seg(t, 1.0, 2.6)))

def bud_orbit(b, t, center, radius, height, speed, phase, tilt=0.0, spin=1.0, s=1.0):
    a = phase + speed * t
    p = Vector(center) + Vector((math.cos(a) * radius, math.sin(a) * radius, height + tilt * math.sin(a)))
    b.location = p
    b.rotation_euler = (0.3 * math.sin(a * 2), 0.25, a + math.pi / 2 + spin * t)
    b.scale = (s, s, s)

def shot2(t, f):  # 4–8s 飛出、繞盒、拉遠帶出地球
    show("case", "buds", "globe")
    rig_at((0, 0, 0)); SUN.data.energy = 2.0
    case_state(1.0, 1.0 - 0.6 * smooth(seg(t, 2.6, 4)))
    for b, sd, ph in ((BUD_L, 1, 0.0), (BUD_R, -1, math.pi)):
        p0, _ = bud_in_case(sd); p0 = p0 + Vector((0, 0, 0.35))
        rise = ease_out(seg(t, 0.0, 0.7))
        up = p0 + Vector((0.6 * sd, -0.4, 3.0))
        orbit_t = seg(t, 0.6, 2.8)
        a = ph + (-math.pi / 2) + math.tau * ease_io(orbit_t)
        orb = Vector((math.cos(a) * 5.0, math.sin(a) * 4.0, 4.6 + 0.6 * math.sin(a * 2)))
        if t < 0.6:
            p = vlerp(p0, up, rise)
        else:
            k = smooth(seg(t, 0.6, 0.95))
            p = vlerp(up, orb, k)
        if t > 2.8:  # 往鏡頭外飛走
            k = ease_in(seg(t, 2.8, 4.0))
            p = vlerp(p, Vector((14 * sd, -8, 16)), k)
        b.location = p
        b.rotation_euler = (0.4 * math.sin(t * 5 + ph), 0.3, a + math.pi / 2 + 2.5 * t)
        b.scale = (1, 1, 1)
    k = ease_io(seg(t, 1.8, 4.0))
    camd = lerp(15, 62, k)
    a = 0.1 + 0.5 * t / 4
    tgt = vlerp((0, 0, 3.0), GLOBE_C + Vector((0, 0, 4)), k)
    look((math.sin(a) * camd, -math.cos(a) * camd, lerp(7, 34, k)), tgt, lerp(45, 40, k))
    sky_lerp(("#FFB88C", "#FFE3C4"), ("#8FD3FF", "#D9F1FF"), smooth(seg(t, 0.5, 3.5)))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * lerp(1, 6, k)

def globe_spin(t):
    GLOBE.rotation_euler = (0, 0, 0.12 * t)
    for i, (cl, c) in enumerate(CLOUDS):
        cl.location = Matrix.Rotation(0.05 * t * (1 + 0.2 * i), 3, "Z") @ c * (GLOBE_R + 2.2)

def shot3(t, f):  # 8–12s 繞地球
    show("globe", "buds", "case")
    case_state(0.0, 0.0)
    buds_in_case(); BUD_L.scale = BUD_R.scale = (0, 0, 0)
    rig_at(GLOBE_C, 4.0); SUN.data.energy = 3.0
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 10
    globe_spin(t + 4)
    T = t
    for b, ph in ((BUD_L, 0.0), (BUD_R, 0.5)):
        a = 1.2 + ph + 0.75 * T
        p = GLOBE_C + Matrix.Rotation(0.35, 3, "X") @ Vector((math.cos(a) * 17.5, math.sin(a) * 17.5 - 2, 3.0 * math.sin(a * 1.5)))
        b.location = p
        b.rotation_euler = (0.3, 0.4 * math.sin(T * 3 + ph * 6), a + 2.0 * T)
        b.scale = (2.2, 2.2, 2.2)
    a = -0.15 + 0.22 * t / 4
    look(GLOBE_C + Vector((math.sin(a) * 52, -math.cos(a) * 52, 18 - 3 * t / 4)), GLOBE_C + Vector((0, 0, 1)), 42)
    sky("#7CC8FF", "#E3F4FF")

def city_buds(t, center, s=0.55, r=2.6, h=3.2, speed=1.1):
    for b, ph in ((BUD_L, 0.0), (BUD_R, math.pi)):
        a = ph + speed * t
        b.location = Vector(center) + Vector((math.cos(a) * r, math.sin(a) * r * 0.6 - 0.8, h + 0.35 * math.sin(2 * a + t)))
        b.rotation_euler = (0.35 * math.sin(a), 0.3, a + math.pi / 2)
        b.scale = (s, s, s)

def fly_in(t, center, s, dur=0.9):
    """前 dur 秒耳機從畫面外飛進來。"""
    k = ease_out(seg(t, 0, dur))
    for b, sd in ((BUD_L, 1), (BUD_R, -1)):
        b.location = vlerp(Vector(center) + Vector((-9 * sd, -9, 9)), b.location, k)

def shot4(t, f):  # 12–18 市集
    show("market", "buds")
    rig_at(MK + Vector((0, 0, 0)), 1.2); SUN.data.energy = 1.2
    SUN.rotation_euler = (math.radians(55), 0, math.radians(-30))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 1.2
    city_buds(t, MK + Vector((0, 0.5, 0)), 0.58, 3.0, 3.6)
    fly_in(t, MK, 0.42)
    person_bob(VENDOR, t, 0.0, 0.18 if 0.8 < t < 5.6 else 0.06)
    for i in range(3): person_bob(bpy.data.objects[f"shopper{i}"], t, 0.25 * i, 0.08)
    k = ease_out(seg(t, 0, 1.4))
    a = lerp(-0.6, -0.15, ease_io(t / 6))
    d = lerp(26, 15.5, k)
    look(MK + Vector((math.sin(a) * d, -math.cos(a) * d, lerp(13, 5.4, k))), MK + Vector((0.2, 1.2, 1.8)), 40, dof=MK + Vector((0.2, 2.4, 1.6)), fstop=5.6)
    sky("#FFB37A", "#7A6CF0", 1.0)

def shot5(t, f):  # 18–24 海灘
    show("beach", "buds")
    rig_at(BC, 1.2); SUN.data.energy = 4.0
    SUN.rotation_euler = (math.radians(45), math.radians(-10), math.radians(165))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 0.9
    animate_sea(t + 6)
    city_buds(t, BC + Vector((0, 0.5, 0)), 0.58, 3.2, 3.4, 1.0)
    fly_in(t, BC, 0.42)
    person_bob(SWIMMER, t, 0.0, 0.2 if 0.8 < t < 5.6 else 0.06)
    person_bob(bpy.data.objects["friend"], t, 0.25, 0.1)
    BALL.location = BC + Vector((1.8, 0.6, 0.45 + 1.4 * abs(math.sin(math.pi * t / (BEAT * 2)))))
    BALL.rotation_euler = (t * 2, t * 1.3, 0)
    a = lerp(0.5, 0.15, ease_io(t / 6))
    k = ease_out(seg(t, 0, 1.4))
    d = lerp(24, 14.5, k)
    look(BC + Vector((math.sin(a) * d, -math.cos(a) * d, lerp(10, 4.2, k))), BC + Vector((0, 1.0, 1.7)), 38, dof=BC + Vector((-0.6, 0.2, 1.6)), fstop=5.6)
    sky("#BFF0FF", "#3FA9F5", 1.1)

def shot6(t, f):  # 24–30 街頭樂團
    show("band", "buds")
    rig_at(BD, 1.2); SUN.data.energy = 0.8
    SUN.rotation_euler = (math.radians(50), 0, math.radians(20))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 1.1
    city_buds(t, BD + Vector((0, 0.5, 0)), 0.58, 3.4, 4.0, 1.2)
    fly_in(t, BD, 0.42)
    for i, m in enumerate(MUSICIANS): person_bob(m, t, 0.15 * i, 0.16)
    for i, c in enumerate(CROWD): person_bob(c, t, 0.5 * (i % 2), 0.22 if i == 0 and 0.8 < t < 5.6 else 0.14)
    DRUM.scale = (1, 1, 1 + 0.06 * bounce(t))
    for i, n in enumerate(NOTES):
        u = (t * 0.35 + i / len(NOTES)) % 1.0
        n.location = BD + Vector((-3 + 6 * (i / 9) + 0.6 * math.sin(t * 2 + i), 2.6 - 1.5 * u, 2.0 + 4.5 * u))
        n.rotation_euler = (0, 0.3 * math.sin(t * 3 + i), 0)
        sc = 0.9 * math.sin(math.pi * u); n.scale = (sc, sc, sc)
    for c, p0, ph in CONFETTI:
        z = (p0.z - 1.2 * t) % 7.5
        c.location = BD + Vector((p0.x + 0.3 * math.sin(t * 2 + ph), p0.y, z))
        c.rotation_euler = (t * 3 + ph, t * 2 + ph, ph)
    a = lerp(-0.35, 0.2, ease_io(t / 6))
    k = ease_out(seg(t, 0, 1.4))
    d = lerp(24, 15, k)
    look(BD + Vector((math.sin(a) * d, -math.cos(a) * d, lerp(12, 5.0, k))), BD + Vector((0, 1.0, 1.9)), 38, dof=BD + Vector((0.6, -1.4, 1.6)), fstop=5.6)
    sky("#3B2B6E", "#141233", 0.7)

def studio_buds(t, center, s=1.0, spin=0.35, gap=1.7):
    for b, sd in ((BUD_L, 1), (BUD_R, -1)):
        b.location = Vector(center) + Vector((gap * sd, 0, 0.12 * math.sin(t * 2 + sd)))
        b.rotation_euler = (0.15, -0.25 * sd, spin * t * sd + 0.4 * sd)
        b.scale = (s, s, s)

def shot7(t, f):  # 30–36 浪打上耳機、水花慢動作、甩乾、閃光
    show("buds", "beach", "fx")
    center = BC + Vector((0.6, -5.2, 2.2))
    rig_at(center, 1.0); SUN.data.energy = 4.0
    SUN.rotation_euler = (math.radians(45), math.radians(-10), math.radians(165))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 1.0
    BUD_R.scale = (0, 0, 0)
    shake = 0.0
    if 3.2 < t < 4.2: shake = 0.35 * math.sin((t - 3.2) * 40) * (1 - (t - 3.2))
    BUD_L.location = center + Vector((0, 0, 0.15 * math.sin(t * 1.5)))
    BUD_L.rotation_euler = (0.1 + 0.4 * shake, -0.15, 0.3 + 0.12 * t + shake)
    BUD_L.scale = (1.15, 1.15, 1.15)
    # 一道浪往岸邊推，0.9s 打到耳機後退去
    crest = lerp(-16.0, -5.2, ease_out(seg(t, 0.0, 1.0))) - 6.0 * ease_in(seg(t, 1.3, 3.0))
    height = 1.5 * smooth(seg(t, 0.0, 0.8)) * (1 - smooth(seg(t, 1.1, 2.4)))
    animate_sea(t + 2, 0.2, (crest - BC.y, height))
    # 水花：慢動作拋物線（時間放慢約 3.5 倍）
    for d_, p0, v0, s in DROPS:
        tt = max(0.0, t - 0.9) * 0.28
        if t < 0.9:
            d_.scale = (0, 0, 0); continue
        d_.location = center + Vector((0, 0, -1.6)) + p0 + v0 * tt + Vector((0, 0, -9.8 * tt * tt / 2))
        d_.scale = (s, s, s * 1.25)
    # 甩乾：第二批水滴從耳機甩出
    if t > 3.2:
        for d_, p0, v0, s in DROPS[:50]:
            tt = (t - 3.2) * 0.8
            d_.location = center + Vector((0, 0, -1.0)) + Vector((v0.x * 1.2, v0.y * 0.8 - 1, v0.z * 0.4)) * tt + Vector((0, 0, -9.8 * tt * tt / 2))
            d_.scale = (s * 0.7,) * 3
    a = lerp(-0.35, 0.05, ease_io(t / 6))
    d = lerp(14.0, 12.0, ease_io(t / 6))
    look(center + Vector((math.sin(a) * d, -math.cos(a) * d, 3.2)), center + Vector((0, 0, -1.2)), 45, dof=center, fstop=8)
    sky("#BFF0FF", "#3FA9F5", 1.1)

def shot8(t, f):  # 36–44 噪音色塊被消除
    show("buds", "studio")
    WAVE.hide_render = True
    for d_, *_ in DROPS: d_.hide_render = True
    center = ST + Vector((0, 0, 0.6))
    rig_at(center); SUN.data.energy = 2.0
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 1.0
    studio_buds(t, center + Vector((0, 0, 0)), 1.0, 0.25, 1.7)
    hit = 2.0
    g = smooth(seg(t, hit - 0.1, hit + 0.15)) * (1 - 0.6 * smooth(seg(t, hit + 0.6, hit + 2.0)))
    bud_glow(g)
    for i, (n_, p0, s, ph) in enumerate(NOISE):
        n_.hide_render = False
        jit = Vector((math.sin(t * 13 + ph), math.cos(t * 11 + ph * 2), math.sin(t * 17 + ph * 3))) * 0.35
        pop_at = hit + 0.02 * i
        k = smooth(seg(t, pop_at, pop_at + 0.25))
        grow = back_out(seg(t, 0.0 + 0.02 * i, 0.4 + 0.02 * i), 2.5)
        sc = s * grow * (1 + 0.25 * math.sin(t * 20 + ph)) * (1 - k) + 0.0
        pos = center + p0 + jit * (1 - k) + (p0.normalized() * 3.0) * k
        n_.location = pos; n_.rotation_euler = (t * 3 + ph, t * 2.3 + ph, ph); n_.scale = (sc, sc, sc)
    a = lerp(-0.1, 0.25, ease_io(t / 8))
    d = lerp(15, 11, ease_io(t / 8))
    look(center + Vector((math.sin(a) * d, -math.cos(a) * d, 2.2)), center + Vector((0, 0, -0.9)), 45)
    k = smooth(seg(t, hit, hit + 1.2))
    sky_lerp(("#FF8A65", "#FFC94D"), ("#E9E4FF", "#C9D8FF"), k, 1.0)

def shot9(t, f):  # 44–50 夕陽、柄部特寫
    show("buds", "studio")
    for n_, *_ in NOISE: n_.hide_render = True
    WAVE.hide_render = True
    for d_, *_ in DROPS: d_.hide_render = True
    bud_glow(0)
    center = ST + Vector((0, 0, 0.6))
    rig_at(center); SUN.data.energy = 3.5
    SUN.rotation_euler = (math.radians(75), 0, math.radians(200))
    SUN.data.color = (1.0, 0.7, 0.45)
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 0.9
    RIM.data.color = (1.0, 0.6, 0.35)
    BUD_R.scale = (0, 0, 0)
    BUD_L.location = center
    BUD_L.rotation_euler = (0.12, -0.2, -0.6 + 0.55 * t)
    BUD_L.scale = (1.2, 1.2, 1.2)
    k = ease_io(t / 6)
    a = lerp(-0.45, 0.35, k)
    d = lerp(12.0, 9.5, k)
    look(center + Vector((math.sin(a) * d, -math.cos(a) * d, lerp(0.8, -0.6, k))), center + Vector((0, 0, -1.5)), lerp(35, 32, k),
         dof=center + Vector((0, 0, -1.4)), fstop=4)
    sky("#FFB06B", "#FF6F91", 1.1)

def shot10(t, f):  # 50–56 地球三城亮起、光環
    show("globe", "buds")
    SUN.data.color = (1, 1, 1); RIM.data.color = (1.0, 0.9, 0.85)
    bud_glow(0)
    rig_at(GLOBE_C, 4.0); SUN.data.energy = 3.0
    SUN.rotation_euler = (math.radians(40), math.radians(10), math.radians(30))
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base * 10
    GLOBE.rotation_euler = (0, 0, 0.0)
    for i, (cl, c) in enumerate(CLOUDS):
        cl.location = Matrix.Rotation(0.05 * (t + 12) * (1 + 0.2 * i), 3, "Z") @ c * (GLOBE_R + 2.2)
    for i, mk in enumerate(MARKERS):
        k = back_out(seg(t, 0.2 + 0.5 * i, 0.6 + 0.5 * i), 2.5)
        pulse = 1 + 0.15 * bounce(t)
        mk.scale = (k * pulse,) * 3
    M["marker"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 6.0
    hk = ease_out(seg(t, 1.8, 3.0))
    HALO.scale = (hk, hk, hk)
    M["halo"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 5.0 * hk
    for b, ph in ((BUD_L, 0.0), (BUD_R, math.pi)):
        a = ph + 0.9 * t
        loc_ = GLOBE.matrix_world @ (Matrix.Rotation(a, 3, _n) @ (CITY_DIRS[0] * (GLOBE_R + 3.2)))
        b.location = loc_
        b.rotation_euler = (0.3, 0.3, a + 1.6 + 2 * t)
        b.scale = (2.0, 2.0, 2.0)
    a = -0.05 + 0.16 * t / 6
    d = lerp(46, 52, ease_io(t / 6))
    look(GLOBE_C + Vector((math.sin(a) * d, -math.cos(a) * d, 12)), GLOBE_C + Vector((0, 0, 0)), 42)
    sky("#9CD8FF", "#4B7BE5", 1.0)

def shot11(t, f):  # 56–60 飛回盒子、合蓋
    show("case", "buds")
    rig_at((0, 0, 0)); SUN.data.energy = 1.5
    for o_, base in zip(LIGHT_RIG, (2500, 900, 1800)): o_.data.energy = base
    bud_glow(0)
    close = ease_in(seg(t, 1.55, 2.0))
    case_state(1.0 - close, 1.0 - close)
    for b, sd in ((BUD_L, 1), (BUD_R, -1)):
        p_end, _ = bud_in_case(sd)
        k = ease_io(seg(t, 0.0, 1.5))
        a = math.pi * 1.5 * (1 - k) * sd
        start = Vector((7 * sd, -6, 8))
        arc = vlerp(start, p_end + Vector((0, 0, 2.5)), k)
        p = arc + Vector((math.cos(a) * 1.5 * (1 - k), math.sin(a) * 1.5 * (1 - k), 0))
        drop = smooth(seg(t, 1.1, 1.5))
        p = vlerp(p, p_end, drop) if t > 1.1 else p
        b.location = p
        _, e_end = bud_in_case(sd)
        b.rotation_euler = (lerp(0.6, e_end.x, k), 0.0, lerp(3.0 * sd, e_end.z, k))
        b.scale = (1, 1, 1)
    k = ease_out(seg(t, 0, 2.5))
    look(vlerp((6, -19, 9), (0, -19, 5.0), k), vlerp((0, 0, 3.2), (0, 0, 3.4), k), 50)
    sky("#BFE6FF", "#7FC4FF", 1.0)

SHOT_FN = {1: shot1, 2: shot2, 3: shot3, 4: shot4, 5: shot5, 6: shot6, 7: shot7, 8: shot8, 9: shot9, 10: shot10, 11: shot11}
BUBBLE_ANCHOR = {4: (VENDOR, (0, 0, 1.95)), 5: (SWIMMER, (0, 0, 1.95)), 6: (FAN, (0, 0, 1.95)), 7: (BUD_L, (0, 0, 0.35))}

# ---------------------------------------------------------------- 渲染
def reset():
    SUN.data.color = (1, 1, 1); RIM.data.color = (1.0, 0.9, 0.85)
    case_state(0, 0); bud_glow(0)
    for o, rot in zip(LIGHT_RIG, RIG_ROT): o.rotation_euler = rot
    for c in COLL.values():
        for o in c.objects:
            if o.name.startswith(("noise", "drop", "wave")): o.hide_render = False

for sid in SHOTS:
    sh = next(s for s in TL["shots"] if s["id"] == sid)
    n = int(round((sh["end"] - sh["start"]) * FPS))
    d = os.path.join(OUT, f"shot{sid:02d}")
    os.makedirs(d, exist_ok=True)
    reset()
    frames = [int(x) for x in ONLY.split(",")] if ONLY else [f for f in range(0, n, STEP) if f % SHARD[1] == SHARD[0]]
    anchors = {}
    for f in frames:
        t = f / FPS
        SHOT_FN[sid](t, f)
        bpy.context.view_layer.update()
        if sid in BUBBLE_ANCHOR:
            p = world_to_camera_view(scene, CAM, head_world(*BUBBLE_ANCHOR[sid]))
            anchors[f] = [p.x, 1 - p.y]
        path = os.path.join(d, f"{f:04d}.png")
        if ANCHORS_ONLY or (os.path.exists(path) and not ONLY):
            continue
        r.filepath = path
        bpy.ops.render.render(write_still=True)
        print(f"[shot{sid:02d}] {f + 1}/{n}", flush=True)
    if anchors:
        old = {}
        ap = os.path.join(d, f"anchors_{SHARD[0]}.json")
        if os.path.exists(ap): old = json.load(open(ap))
        old.update({str(k): v for k, v in anchors.items()})
        json.dump(old, open(ap, "w"))
print("DONE", SHOTS)
